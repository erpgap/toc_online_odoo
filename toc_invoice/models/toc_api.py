import requests
from odoo import models, fields
import base64
from urllib.parse import urlparse, parse_qs, urlencode

from odoo.addons.toc_invoice.utils import redirect_uri, auth_url, token_url


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

        url_aux = f"{self.auth_url}/auth?"
        params = {
            "client_id": client_id1,
            "redirect_uri": self.redirect_uri,
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
        self.client_id = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
        self.client_secret = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_secret')

        client_id1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
        client_secret1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_secret')


        client_credentials = f"{client_id1}:{client_secret1}"
        base64_credentials = base64.b64encode(client_credentials.encode("utf-8")).decode("utf-8")
        print(f"Base64 Credentials: {base64_credentials}")

        payload = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": self.redirect_uri
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {base64_credentials}"
        }

        try:
            response = requests.post(self.token_url, data=payload, headers=headers)
            print(f"Response Status Code: {response.status_code}")
            print(f"Response Body: {response.text}")

            if response.status_code == 200:
                return response.json()
            else:
                return {"error": response.json()}
        except Exception as e:
            return {"error": f"Request error: {str(e)}"}

    def get_access_token(self, authorization_code):
        """
            get the access_token.
        """
        tokens = self._get_tokens(authorization_code)
        if "access_token" in tokens:
            return tokens["access_token"]
        else:
            return {"error": tokens.get("error")}

    def get_refresh_token(self, authorization_code):
        """
         get the refresh_token.
        """
        tokens = self._get_tokens(authorization_code)
        if "refresh_token" in tokens:
            return tokens["refresh_token"]
        else:
            return {"error": tokens.get("error")}