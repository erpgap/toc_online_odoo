import requests
from odoo import models, fields, _
import base64
from urllib.parse import urlparse, parse_qs

from odoo.addons.toc_invoice.utils import redirect_uri, auth_url, token_url
from datetime import datetime, timedelta
from odoo.exceptions import UserError


class TocAPI(models.AbstractModel):
    _name = 'toc.api'
    _description = 'TOConline API'

    client_id = fields.Char(string="Client ID")
    client_secret = fields.Char(string="Client Secret")

    def get_authorization_url(self):
        company = self.env.company.sudo()
        client_id = company.toc_online_client_id
        client_secret = company.toc_online_client_secret

        if not client_id or not client_secret:
            raise UserError(_("Client ID and/or Client Secret not configured."))

        url_aux = f"{auth_url}/auth?"
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "commercial"
        }

        response = requests.get(url_aux, params=params, headers={"Content-Type": "application/json"}, allow_redirects=False)
        if response.status_code == 302:
            redirect_url = response.headers.get('Location')
            return redirect_url if redirect_url else {"error": "'Location' header not found in response."}
        return {"error": f"Error obtaining authorization: {response.status_code}"}

    def _extract_authorization_code_from_url(self, url):
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        return query_params.get("code", [None])[0]

    def _get_tokens(self, authorization_code):
        company = self.env.company.sudo()
        config = self.env['ir.config_parameter'].sudo()
        client_id = company.toc_online_client_id
        client_secret = company.toc_online_client_secret

        if not client_id or not client_secret:
            raise UserError(_("Client ID and/or Client Secret not configured. Please configure them in company settings."))

        client_credentials = f"{client_id}:{client_secret}"
        base64_credentials = base64.b64encode(client_credentials.encode("utf-8")).decode("utf-8")

        payload = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": redirect_uri
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {base64_credentials}"
        }

        response = requests.post(token_url, data=payload, headers=headers)
        if response.status_code == 200:
            tokens = response.json()
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            expires_in = tokens.get("expires_in", 3600)
            expiry_datetime = datetime.now() + timedelta(seconds=expires_in)

            if not refresh_token:
                raise UserError(_("Error: Refresh token not found in TOConline response."))

            config.set_param('toc_online.refresh_token', refresh_token)
            config.set_param('toc_online.access_token', access_token)
            config.set_param('toc_online.token_expiry', expiry_datetime.strftime("%Y-%m-%d %H:%M:%S"))

            return {"access_token": access_token, "refresh_token": refresh_token}
        else:
            raise UserError(_(f"Error getting tokens: {response.text}"))

    def get_access_token(self):
        company = self.env.company.sudo()
        config = self.env['ir.config_parameter'].sudo()

        # ✅ Validar client_id/client_secret antes de continuar
        if not company.toc_online_client_id or not company.toc_online_client_secret:
            raise UserError(_("Client ID and/or Client Secret not configured. Cannot proceed with TOConline operation."))

        access_token = config.get_param('toc_online.access_token')

        if not access_token or self.is_token_expired():
            try:
                access_token = self.refresh_access_token()
            except UserError:
                config.set_param('toc_online.access_token', '')
                config.set_param('toc_online.token_expiry', '')
                config.set_param('toc_online.refresh_token', '')

                redirect_auth_url = self.get_authorization_url()
                code = self._extract_authorization_code_from_url(redirect_auth_url)
                if not code:
                    raise UserError(_("Unable to extract code from URL"))

                tokens = self._get_tokens(code)
                access_token = tokens.get("access_token")
                if not access_token:
                    raise UserError(_("Failed to get access_token with authorization code."))

        return access_token

    def get_refresh_token(self, authorization_code):
        tokens = self._get_tokens(authorization_code)
        return tokens.get("refresh_token") or {"error": tokens.get("error")}

    def get_expires_in(self, authorization_code):
        tokens = self._get_tokens(authorization_code)
        return tokens.get("expires_in") or {"error": tokens.get("error")}

    def is_token_expired(self):
        config = self.env['ir.config_parameter'].sudo()
        token_expiry = config.get_param('toc_online.token_expiry')
        if not token_expiry:
            return True
        try:
            expiry_dt = datetime.strptime(token_expiry, "%Y-%m-%d %H:%M:%S")
            return expiry_dt < datetime.now()
        except Exception:
            return True

    def refresh_access_token(self):
        config = self.env['ir.config_parameter'].sudo()
        refresh_token = config.get_param('toc_online.refresh_token')
        company = self.env.company.sudo()

        client_id = company.toc_online_client_id
        client_secret = company.toc_online_client_secret

        if not client_id or not client_secret:
            raise UserError(_("Client ID and/or Client Secret not configured."))

        if not refresh_token:
            raise UserError(_("Refresh token not found. Please authenticate again via TOConline login button."))

        client_credentials = f"{client_id}:{client_secret}"
        base64_credentials = base64.b64encode(client_credentials.encode("utf-8")).decode("utf-8")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "commercial"
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {base64_credentials}"
        }

        response = requests.post(token_url, data=payload, headers=headers)

        if response.status_code == 200:
            tokens = response.json()
            access_token = tokens.get("access_token")
            refresh_token_response = tokens.get("refresh_token")
            expires_in = tokens.get("expires_in", 3600)
            expiry_datetime = datetime.now() + timedelta(seconds=expires_in)

            config.set_param('toc_online.access_token', access_token)
            config.set_param('toc_online.token_expiry', expiry_datetime.strftime("%Y-%m-%d %H:%M:%S"))
            if refresh_token_response:
                config.set_param('toc_online.refresh_token', refresh_token_response)
            return access_token

        elif response.status_code == 401:
            config.set_param('toc_online.refresh_token', '')
            config.set_param('toc_online.access_token', '')
            config.set_param('toc_online.token_expiry', '')

            auth_url_response = self.get_authorization_url()
            if isinstance(auth_url_response, dict) and "error" in auth_url_response:
                raise UserError(auth_url_response["error"])

            raise UserError(_(f"Access to TOConline has expired. Please re-authenticate:\n\n{auth_url_response}"))

        else:
            raise UserError(f"Error renewing access_token: {response.text}")
