import requests
from odoo import models, fields
import base64
from urllib.parse import urlparse, parse_qs, urlencode

class TocAPI(models.AbstractModel):
    _name = 'toc.api'
    _description = 'TOConline API'

    redirect_uri = "https://5d54-2001-818-de5d-da00-ab74-3e1f-b1bc-38f2.ngrok-free.app/oauth/callback"
    auth_url = "https://app9.toconline.pt/oauth"
    token_url = "https://app9.toconline.pt/oauth/token"

    client_id = fields.Char(string="Client ID")
    client_secret = fields.Char(string="Client Secret")

    def get_authorization_url(self):
        """
        Obtém a URL de redirecionamento da API TOConline.
        """
        self.client_id = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
        self.client_secret = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_secret')

        client_id1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')

        url_aux = f"{self.auth_url}/auth?"
        # Criar a URL de autenticação com parâmetros
        params = {
            "client_id": client_id1,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "commercial"
        }

        headers = {
            "Content-Type": "application/json"
        }


        print(f"Fazendo requisição para: {url_aux}")

        print(f"este é o meu client_id {client_id1}")
        print(f"Parâmetros: {params}")
        print(f"Headers: {headers}")

        response = requests.get(url_aux, params=params, headers=headers, allow_redirects=False)

        print(f"Resposta da API: {response.status_code}")
        print(f"Cabeçalhos da resposta: {response.headers}")
        print(f"Corpo da resposta: {response.text}")

        # Verifica se há um redirecionamento (status code 302)
        if response.status_code == 302:
            # Extrai a URL de redirecionamento do cabeçalho 'Location'
            redirect_url = response.headers.get('Location')
            if redirect_url:
                return redirect_url  # Retorna a URL de redirecionamento
            else:
                return {"error": "Cabeçalho 'Location' não encontrado na resposta."}
        else:
            return {"error": f"Erro ao obter autorização: {response.status_code}"}

    def _extract_authorization_code_from_url(self, url):
        """
        Extrai o código de autorização da URL de callback.
        """
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        return query_params.get("code", [None])[0]

    def _get_tokens(self, authorization_code):
        """
        Função interna que troca o authorization_code pelo access_token e refresh_token.
        """
        self.client_id = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
        self.client_secret = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_secret')

        client_id1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
        client_secret1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_secret')


        # Verifique as credenciais
        print(f"Client ID: {self.client_id}")
        print(f"este é o meu client_id teste {client_id1}")
        print(f"este é o meu secret  teste {client_secret1}")
        print(f"Client Secret: {self.client_secret}")

        # Codificação Base64 das credenciais
        client_credentials = f"{client_id1}:{client_secret1}"
        base64_credentials = base64.b64encode(client_credentials.encode("utf-8")).decode("utf-8")
        print(f"Base64 Credentials: {base64_credentials}")

        # Payload da requisição
        payload = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": self.redirect_uri
        }
        print(f"Payload: {payload}")

        # Headers da requisição
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {base64_credentials}"
        }
        print(f"Headers: {headers}")

        try:
            # Faz a requisição para obter os tokens
            response = requests.post(self.token_url, data=payload, headers=headers)
            print(f"Response Status Code: {response.status_code}")
            print(f"Response Body: {response.text}")

            if response.status_code == 200:
                return response.json()
            else:
                return {"error": response.json()}
        except Exception as e:
            return {"error": f"Erro na requisição: {str(e)}"}

    def get_access_token(self, authorization_code):
        """
        Obtém o access_token.
        """
        tokens = self._get_tokens(authorization_code)
        if "access_token" in tokens:
            return tokens["access_token"]
        else:
            return {"error": tokens.get("error")}

    def get_refresh_token(self, authorization_code):
        """
        Obtém o refresh_token.
        """
        tokens = self._get_tokens(authorization_code)
        if "refresh_token" in tokens:
            return tokens["refresh_token"]
        else:
            return {"error": tokens.get("error")}