import requests
from odoo import models, fields
import base64
from urllib.parse import urlparse, parse_qs

from odoo.addons.toc_invoice.utils import redirect_uri, auth_url, token_url
from datetime import datetime, timedelta

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
        print(f"Base64 Credentials: {base64_credentials}")

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
            print(f"Response Status Code: {response.status_code}")
            print(f"Response Body: {response.text}")

            if response.status_code == 200:
                return response.json()
            else:
                return {"error": response.json()}
        except Exception as e:
            return {"error": f"Request error: {str(e)}"}

    def get_access_token(self):
        """
        Gets the access token, renewing it if necessary.
        """
        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')

        if access_token:
            if self.is_token_expired():
                return self.refresh_access_token()
            return access_token
        else:
            return self.refresh_access_token()

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
        """
        Checks if the access token has expired.
        """
        token_expiry = self.env['ir.config_parameter'].sudo().get_param('toc_online.token_expiry')
        if token_expiry:
            expiry_datetime = datetime.strptime(token_expiry, "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expiry_datetime:
                return True
        return False

    def refresh_access_token(self):
        """
            Automatically renew access token.
        """
        authorization_code = self.env['ir.config_parameter'].sudo().get_param('toc_online.authorization_code')
        if authorization_code:
            tokens = self._get_tokens(authorization_code)
            if "access_token" in tokens:
                access_token = tokens["access_token"]
                expires_in = tokens.get("expires_in", 3600)
                expiry_datetime = datetime.now() + timedelta(seconds=expires_in)
                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', access_token)
                self.env['ir.config_parameter'].sudo().set_param('toc_online.token_expiry',
                                                                 expiry_datetime.strftime("%Y-%m-%d %H:%M:%S"))
                return access_token
        return None

