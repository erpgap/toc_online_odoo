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
        """
            Gets the redirect URL from the TOConline API.
        """
        self.client_id = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
        self.client_secret = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_secret')

        client_id1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')

        url_aux = f"{auth_url}/auth?"
        params = {
            "client_id": client_id1,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "commercial"
        }
        headers = {
            "Content-Type": "application/json"
        }

        response = requests.get(url_aux, params=params, headers=headers, allow_redirects=False)
        if response.status_code == 302:
            redirect_url = response.headers.get('Location')
            if redirect_url:
                return redirect_url
            else:
                return {"error": "'Location' header not found in response."}
        else:
            return {"error": f"Error obtaining authorization: {response.status_code}"}

    def _extract_authorization_code_from_url(self, url):
        """
        Extracts the authorization code from the callback URL.
        """
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        return query_params.get("code", [None])[0]

    def _get_tokens(self, authorization_code):
        """
        Internal function that exchanges authorization_code for access_token and refresh_token.
        """


        client_id1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
        client_secret1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_secret')

        client_credentials = f"{client_id1}:{client_secret1}"
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

        try:
            response = requests.post(token_url, data=payload, headers=headers)

            if response.status_code == 200:
                tokens = response.json()
                access_token = tokens.get("access_token")
                refresh_token = tokens.get("refresh_token")

                expires_in = tokens.get("expires_in", 3600)
                expiry_datetime = datetime.now() + timedelta(seconds=expires_in)

                if refresh_token:
                    self.env['ir.config_parameter'].sudo().set_param('toc_online.refresh_token', refresh_token)
                else:
                    raise UserError(_("Error: Refresh token not found in TOConline response."))

                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', access_token)
                self.env['ir.config_parameter'].sudo().set_param('toc_online.token_expiry',
                                                                 expiry_datetime.strftime("%Y-%m-%d %H:%M:%S"))



                return {"access_token": access_token, "refresh_token": refresh_token}
            else:
                raise UserError(_(f"error getting tokens: {response.text}"))
        except Exception as e:
            raise UserError(_(f"Error on comunication with TOCOnline: {str(e)}"))

    def get_access_token(self):
        """
        Returns the access_token if it is valid.
        Otherwise, it tries to renew it with the refresh_token.
        If this is not possible, it requests new authentication.
        """
        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
        token_expiry = self.env['ir.config_parameter'].sudo().get_param('toc_online.token_expiry')


        Result = self.is_token_expired()

        print("ESTE é o resultado da expiração" , Result)
        print("Access Token atual:", access_token)
        print("Expiração do Token:", token_expiry)

        if not access_token or self.is_token_expired():
            print("Token missing or expired. Trying to renew with refresh_token...")

            try:
                access_token = self.refresh_access_token()
            except UserError as refresh_error:
                print("Failed to renew with refresh_token:", refresh_error)
                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', '')
                self.env['ir.config_parameter'].sudo().set_param('toc_online.token_expiry', '')
                self.env['ir.config_parameter'].sudo().set_param('toc_online.refresh_token', '')

                redirect_auth_url = self.get_authorization_url()

                code = self._extract_authorization_code_from_url(redirect_auth_url)

                if not code:
                    raise UserError(_(
                            f"Unable to extract code from URL"))

                tokens = self._get_tokens(code)
                access_token = tokens.get("access_token")

                if not access_token:
                    raise UserError(_("Failed to get access_token with authorization code."))

        return access_token

    def get_refresh_token(self, authorization_code):
        """
         get the refresh_token
        """
        tokens = self._get_tokens(authorization_code)
        if "refresh_token" in tokens:
            return tokens["refresh_token"]
        else:
            return {"error": tokens.get("error")}

    def get_expires_in(self, authorization_code):
        """
         get the expires_in
        """
        tokens = self._get_tokens(authorization_code)
        if "expires_in" in tokens:
            return tokens["expires_in"]
        else:
            return {"error": tokens.get("error")}

    def is_token_expired(self):
        """ Checks if the token is expired. """
        token_expiry = self.env['ir.config_parameter'].sudo().get_param('toc_online.token_expiry')
        if not token_expiry:
            return True

        try:
            token_expiry = datetime.strptime(token_expiry, "%Y-%m-%d %H:%M:%S")
            if token_expiry < datetime.now():
                return True
        except Exception as e:
            return True
        return False

    def refresh_access_token(self):
        """
       Renews the access_token using the saved refresh_token.
       If this is not possible (e.g., refresh expired), it requests manual authentication from the user again.
        """
        refresh_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.refresh_token')


        if not refresh_token:
            raise UserError(
                _("Refresh token not found. Please authenticate again via TOConline login button.")
            )

        client_id = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
        client_secret = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_secret')

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


        try:
            response = requests.post(token_url, data=payload, headers=headers)

            if response.status_code == 200:
                tokens = response.json()
                access_token = tokens.get("access_token")
                refresh_token_response = tokens.get("refresh_token")
                expires_in = tokens.get("expires_in", 3600)
                expiry_datetime = datetime.now() + timedelta(seconds=expires_in)

                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', access_token)
                self.env['ir.config_parameter'].sudo().set_param(
                    'toc_online.token_expiry', expiry_datetime.strftime("%Y-%m-%d %H:%M:%S"))

                if refresh_token_response:
                    self.env['ir.config_parameter'].sudo().set_param('toc_online.refresh_token', refresh_token_response)
                    print("New refresh_token saved:", refresh_token_response)
                else:
                    print("Warning: New refresh_token not returned. Keeping the previous one.")

                print("New access_token:", access_token)
                return access_token

            elif response.status_code == 401:
                print("Error 401: The refresh_token is expired or invalid.")
                self.env['ir.config_parameter'].sudo().set_param('toc_online.refresh_token', '')
                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', '')
                self.env['ir.config_parameter'].sudo().set_param('toc_online.token_expiry', '')

                auth_url = self.get_authorization_url()
                if isinstance(auth_url, dict) and "error" in auth_url:
                    raise UserError(auth_url["error"])

                raise UserError(
                    _(f"Access to TOConline has expired. Please click the link below to re-authenticate.:\n\n{auth_url}")
                )

            else:
                raise UserError(f"Error renewing access_token: {response.text}")

        except Exception as e:
            raise UserError(f"Error communicating with TOConline: {str(e)}")





