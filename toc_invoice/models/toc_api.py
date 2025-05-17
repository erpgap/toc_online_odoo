import requests
from gevent.resolver.cares import Result
from odoo import models, fields
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

        print("estes são os parametros enviados",params)
        response = requests.get(url_aux, params=params, headers=headers, allow_redirects=False)

        print("esta é a resposta" , response)
        if response.status_code == 302:
            redirect_url = response.headers.get('Location')
            print("isto é o teoricamente retorna ", redirect_url)
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

        print("cliente id :" , client_id1)
        print("segredo de cliente :" , client_secret1)
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
            print("POST para:", token_url)
            print("Headers:", headers)
            print("Payload que vai ser enviado:")
            print(payload)

            response = requests.post(token_url, data=payload, headers=headers)

            if response.status_code == 200:
                tokens = response.json()
                access_token = tokens.get("access_token")
                refresh_token = tokens.get("refresh_token")

                print("o token" , access_token)
                print("o refresh" , refresh_token)
                expires_in = tokens.get("expires_in", 3600)
                expiry_datetime = datetime.now() + timedelta(seconds=expires_in)

                # Verifique se o refresh_token está presente
                if refresh_token:
                    self.env['ir.config_parameter'].sudo().set_param('toc_online.refresh_token', refresh_token)
                else:
                    raise UserError("Erro: Refresh token não encontrado na resposta da TOConline.")

                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', access_token)
                self.env['ir.config_parameter'].sudo().set_param('toc_online.token_expiry',
                                                                 expiry_datetime.strftime("%Y-%m-%d %H:%M:%S"))



                return {"access_token": access_token, "refresh_token": refresh_token}
            else:
                raise UserError(f"Erro ao obter tokens: {response.text}")
        except Exception as e:
            raise UserError(f"Erro na comunicação com TOConline: {str(e)}")

    def get_access_token(self):
        """
        Retorna o access_token se estiver válido.
        Caso contrário, tenta renovar com o refresh_token.
        Se não for possível, solicita nova autenticação.
        """
        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
        token_expiry = self.env['ir.config_parameter'].sudo().get_param('toc_online.token_expiry')


        Result = self.is_token_expired()

        print("ESTE é o resultado da expiração" , Result)
        print("Access Token atual:", access_token)
        print("Expiração do Token:", token_expiry)

        if not access_token or self.is_token_expired():
            print("Token ausente ou expirado. Tentando renovar com refresh_token...")

            try:
                access_token = self.refresh_access_token()
            except UserError as refresh_error:
                print("Falha ao renovar com refresh_token:", refresh_error)
                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', '')
                self.env['ir.config_parameter'].sudo().set_param('toc_online.token_expiry', '')
                self.env['ir.config_parameter'].sudo().set_param('toc_online.refresh_token', '')

                redirect_auth_url = self.get_authorization_url()
                print("URL de redirecionamento gerada:", redirect_auth_url)

                code = self._extract_authorization_code_from_url(redirect_auth_url)
                print("Código de autorização extraído:", code)

                if not code:
                    raise UserError(
                        f"Não foi possível extrair o código da URL. A autenticação automática falhou. Acesse: {redirect_auth_url}")

                tokens = self._get_tokens(code)
                access_token = tokens.get("access_token")

                if not access_token:
                    raise UserError("Falha ao obter access_token com o código de autorização.")

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
        """ Verifica se o token está expirado. """
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
        Renova o access_token usando o refresh_token guardado.
        Se não for possível (ex: refresh expirado), solicita nova autenticação manual ao usuário.
        """
        refresh_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.refresh_token')
        print("Refresh token atual:", refresh_token)

        expi = self.env['ir.config_parameter'].sudo().get_param('toc_online.token_expiry')
        print("Este é o tempo de expiração:", expi)

        if not refresh_token:
            raise UserError(
                "Refresh token não encontrado. Por favor, autentique-se novamente através do botão de login TOConline."
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

        print("Payload para renovação:", payload)
        print("Headers:", headers)

        try:
            response = requests.post(token_url, data=payload, headers=headers)
            print("Resposta do servidor:", response)

            if response.status_code == 200:
                tokens = response.json()
                access_token = tokens.get("access_token")
                refresh_token_response = tokens.get("refresh_token")
                expires_in = tokens.get("expires_in", 3600)
                expiry_datetime = datetime.now() + timedelta(seconds=expires_in)

                # Salva o novo access_token
                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', access_token)
                self.env['ir.config_parameter'].sudo().set_param(
                    'toc_online.token_expiry', expiry_datetime.strftime("%Y-%m-%d %H:%M:%S"))

                if refresh_token_response:
                    self.env['ir.config_parameter'].sudo().set_param('toc_online.refresh_token', refresh_token_response)
                    print("Novo refresh_token salvo:", refresh_token_response)
                else:
                    print("Aviso: Novo refresh_token não retornado. Mantendo o anterior.")

                print("Novo access_token:", access_token)
                return access_token

            elif response.status_code == 401:
                # Token inválido ou expirado: solicitar nova autorização manual
                print("Erro 401: O refresh_token expirou ou é inválido.")
                self.env['ir.config_parameter'].sudo().set_param('toc_online.refresh_token', '')
                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token', '')
                self.env['ir.config_parameter'].sudo().set_param('toc_online.token_expiry', '')

                auth_url = self.get_authorization_url()
                if isinstance(auth_url, dict) and "error" in auth_url:
                    raise UserError(auth_url["error"])

                raise UserError(
                    f"O acesso à TOConline expirou. Por favor, clique no link abaixo para se autenticar novamente:\n\n{auth_url}"
                )

            else:
                raise UserError(f"Erro ao renovar access_token: {response.text}")

        except Exception as e:
            raise UserError(f"Erro na comunicação com TOConline: {str(e)}")





