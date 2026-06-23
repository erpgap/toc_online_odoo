import base64
import json
import logging
import requests
from datetime import timedelta
from urllib.parse import urlparse, parse_qs

from odoo import _, fields
from odoo.exceptions import UserError

from markupsafe import Markup

_logger = logging.getLogger(__name__)

TOC_TIMEOUT = 120


class TocOnlineService:
    """TOConline API service. Follows Odoo Enterprise delivery carrier pattern."""

    def __init__(self, company, env):
        """
        :param company: res.company record
        :param env: Odoo environment (needed for ORM operations)
        """
        self.company = company.sudo()
        self.env = env
        self.base_url = self.company.toc_api_url
        self._access_token = None

    # -----------------------------------------------------------------
    # A. Authentication
    # -----------------------------------------------------------------

    def _ensure_access_token(self):
        if self._access_token:
            return self._access_token
        self._access_token = self._get_access_token()
        return self._access_token

    @property
    def access_token(self):
        return self._ensure_access_token()

    def _get_access_token(self):
        company = self.company
        if not company.toc_online_enabled:
            return None
        self._check_configuration()

        token = company.toc_online_access_token
        if not token or self._is_token_expired():
            try:
                token = self._refresh_access_token()
            except UserError:
                company.write({
                    'toc_online_access_token': False,
                    'toc_online_refresh_token': False,
                    'toc_online_token_expiry': False,
                })
                redirect_auth_url = self._get_authorization_url()
                code = self._extract_authorization_code_from_url(redirect_auth_url)
                if not code:
                    raise UserError(_("Unable to extract code from URL"))
                tokens = self._get_tokens(code)
                token = tokens.get("access_token")
                if not token:
                    raise UserError(_("Failed to get access_token with authorization code."))
        return token

    def _is_token_expired(self):
        token_expiry = self.company.toc_online_token_expiry
        if not token_expiry:
            return True
        return token_expiry < fields.Datetime.now()

    def _refresh_access_token(self):
        company = self.company
        self._check_configuration()
        refresh_token = company.toc_online_refresh_token
        client_id = company.toc_online_client_id
        client_secret = company.toc_online_client_secret

        if not refresh_token:
            raise UserError(
                _("Refresh token not found. Please authenticate again via TOConline login button.")
            )

        client_credentials = f"{client_id}:{client_secret}"
        base64_credentials = base64.b64encode(client_credentials.encode("utf-8")).decode("utf-8")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "commercial",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {base64_credentials}",
        }
        token_url = company.toc_auth_url + '/token'
        response = requests.post(token_url, data=payload, headers=headers)

        if response.status_code == 200:
            tokens = response.json()
            access_token = tokens.get("access_token")
            refresh_token_response = tokens.get("refresh_token")
            expires_in = tokens.get("expires_in", 3600)
            expiry_datetime = fields.Datetime.now() + timedelta(seconds=expires_in)

            vals = {
                'toc_online_access_token': access_token,
                'toc_online_token_expiry': expiry_datetime,
            }
            if refresh_token_response:
                vals['toc_online_refresh_token'] = refresh_token_response
            company.write(vals)
            return access_token

        elif response.status_code == 401:
            company.write({
                'toc_online_access_token': False,
                'toc_online_refresh_token': False,
                'toc_online_token_expiry': False,
            })
            auth_url_response = self._get_authorization_url()
            if isinstance(auth_url_response, dict) and "error" in auth_url_response:
                raise UserError(auth_url_response["error"])
            raise UserError(
                _("Access to TOConline has expired. Please re-authenticate:\n\n%s") % auth_url_response
            )
        else:
            raise UserError(_("Error renewing access_token: %s") % response.text)

    def _get_authorization_url(self):
        company = self.company
        self._check_configuration()
        client_id = company.toc_online_client_id

        url_aux = f"{company.toc_auth_url}/auth?"
        params = {
            "client_id": client_id,
            "redirect_uri": company.toc_redirect_uri,
            "response_type": "code",
            "scope": "commercial",
        }
        response = requests.get(
            url_aux, params=params,
            headers={"Content-Type": "application/json"},
            allow_redirects=False,
        )
        if response.status_code == 302:
            redirect_url = response.headers.get('Location')
            return redirect_url if redirect_url else {"error": "'Location' header not found in response."}
        return {"error": f"Error obtaining authorization: {response.status_code}"}

    def _extract_authorization_code_from_url(self, url):
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        return query_params.get("code", [None])[0]

    def _get_tokens(self, authorization_code):
        company = self.company
        self._check_configuration()
        client_id = company.toc_online_client_id
        client_secret = company.toc_online_client_secret

        client_credentials = f"{client_id}:{client_secret}"
        base64_credentials = base64.b64encode(client_credentials.encode("utf-8")).decode("utf-8")

        payload = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": company.toc_redirect_uri,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {base64_credentials}",
        }
        token_url = company.toc_auth_url + '/token'
        response = requests.post(token_url, data=payload, headers=headers)

        if response.status_code == 200:
            tokens = response.json()
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            expires_in = tokens.get("expires_in", 3600)
            expiry_datetime = fields.Datetime.now() + timedelta(seconds=expires_in)

            if not refresh_token:
                raise UserError(_("Error: Refresh token not found in TOConline response."))

            company.write({
                'toc_online_refresh_token': refresh_token,
                'toc_online_access_token': access_token,
                'toc_online_token_expiry': expiry_datetime,
            })
            return {"access_token": access_token, "refresh_token": refresh_token}
        else:
            raise UserError(_("Error getting tokens: %s") % response.text)

    def _check_configuration(self):
        company = self.company
        if not company.toc_online_enabled:
            raise UserError(_(
                "TOConline integration is not enabled for company '%s'. "
                "Please enable it in Settings > Accounting > TOConline Configuration."
            ) % company.name)
        missing = []
        if not company.toc_online_client_id:
            missing.append(_("Client ID"))
        if not company.toc_online_client_secret:
            missing.append(_("Client Secret"))
        if not company.toc_api_url:
            missing.append(_("API Base URL"))
        if not company.toc_auth_url:
            missing.append(_("OAuth Authentication URL"))
        if not company.toc_redirect_uri:
            missing.append(_("Redirect URI"))
        if missing:
            raise UserError(_(
                "TOConline URL configuration is incomplete. "
                "Please configure the following in Settings > Accounting > TOConline Configuration:\n- %s"
            ) % "\n- ".join(missing))

    # -----------------------------------------------------------------
    # B. HTTP request layer
    # -----------------------------------------------------------------

    def _send_request(self, method, endpoint, payload=None):
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            _logger.info("TOC %s %s", method.upper(), url)
            _logger.debug("Payload: %s", payload)
            response = requests.request(
                method, url, json=payload, headers=headers, timeout=TOC_TIMEOUT,
            )
            _logger.debug("Response [%s]: %s", response.status_code, response.text)
            self._handle_response_errors(response)
            return response
        except requests.exceptions.Timeout:
            _logger.error("Timeout while trying to access %s %s", method.upper(), url)
            raise UserError(
                _("The request to TOConline timed out after %s seconds.") % TOC_TIMEOUT
            )
        except requests.exceptions.RequestException as e:
            _logger.exception("TOConline error on %s %s", method.upper(), url)
            raise UserError(_("Error communicating with TOConline: %s") % str(e))

    def _handle_response_errors(self, response):
        error_text = response.text or "No additional details provided."
        try:
            data = json.loads(response.text)
            if isinstance(data, dict):
                if "error" in data:
                    error_text = data["error"]
                elif "message" in data:
                    error_text = data["message"]
        except (json.JSONDecodeError, TypeError):
            pass

        status = response.status_code
        error_messages = {
            400: _("Bad Request (400): Check the data being sent to TOConline.\n\nDetails:\n%s"),
            401: _("Unauthorized (401): Invalid or expired access token.\n\nDetails:\n%s"),
            403: _("Forbidden (403): You do not have permission to access this resource.\n\nDetails:\n%s"),
            404: _("Not Found (404): The requested resource does not exist on TOConline.\n\nDetails:\n%s"),
            409: _("Conflict (409): The request could not be completed due to a conflict.\n\nDetails:\n%s"),
            422: _("Unprocessable Entity (422): Invalid input data format or validation failed.\n\nDetails:\n%s"),
            500: _("Internal Server Error (500): TOConline encountered an error. Try again later.\n\nDetails:\n%s"),
        }
        if status in error_messages:
            raise UserError(error_messages[status] % error_text)
        elif status >= 400:
            raise UserError(
                _("HTTP Error %s: %s\n\nDetails:\n%s") % (status, response.reason, error_text)
            )

    # -----------------------------------------------------------------
    # C. Customer management
    # -----------------------------------------------------------------

    @staticmethod
    def _sanitize_vat(vat):
        """Strip country prefix and whitespace from VAT, returning digits only."""
        if not vat:
            return "999999990"
        vat = vat.replace(" ", "").strip()
        # Remove leading country code (e.g. "PT" from "PT502992824")
        if len(vat) > 2 and vat[:2].isalpha():
            vat = vat[2:]
        return vat

    def get_or_create_customer(self, partner):
        if partner.toc_online_id:
            return partner.toc_online_id

        tax_number = self._sanitize_vat(partner.vat)
        email = partner.email.strip() if partner.email else ""

        # Search by VAT
        if tax_number != "999999990" and tax_number.isdigit() and len(tax_number) == 9:
            response = self._send_request(
                'GET', f"/api/customers?filter[tax_registration_number]={tax_number}",
            )
            if response.status_code == 200:
                customers = response.json().get('data', [])
                if customers:
                    customer_id = customers[0]["id"]
                    partner.with_company(self.company).sudo().write({'toc_online_id': customer_id})
                    return customer_id

        # Search by email
        if email:
            response = self._send_request('GET', f"/api/customers?filter[email]={email}")
            if response.status_code == 200:
                customers = response.json().get('data', [])
                if customers:
                    customer_id = customers[0]["id"]
                    partner.with_company(self.company).sudo().write({'toc_online_id': customer_id})
                    return customer_id

        # Create new customer
        customer_payload = {
            "data": {
                "type": "customers",
                "attributes": {
                    "tax_registration_number": tax_number,
                    "business_name": partner.name,
                    "contact_name": partner.name,
                    "website": partner.website or "",
                    "phone_number": partner.phone or "",
                    "mobile_number": getattr(partner, "mobile", "") or "",
                    "email": email,
                    "observations": "",
                    "internal_observations": "",
                    "is_tax_exempt": False,
                    "active": True,
                    "country_iso_alpha_2": partner.country_id.code if partner.country_id else None,
                },
            }
        }
        response = self._send_request('POST', "/api/customers", payload=customer_payload)
        if response.status_code in (200, 201):
            customer_id = response.json()["data"]["id"]
            partner.with_company(self.company).sudo().write({'toc_online_id': customer_id})
            return customer_id
        else:
            raise UserError(_("Error creating customer in TOConline: %s") % response.text)

    def update_customer(self, partner):
        customer_id = partner.sudo().with_company(self.company).toc_online_id
        if not customer_id:
            return

        tax_number = partner.vat.replace(" ", "").strip() if partner.vat else "999999990"
        email = partner.email.strip() if partner.email else ""

        customer_payload = {
            "data": {
                "type": "customers",
                "id": customer_id,
                "attributes": {
                    "tax_registration_number": tax_number,
                    "business_name": partner.name,
                    "contact_name": partner.name,
                    "website": partner.website or "",
                    "phone_number": partner.phone or "",
                    "mobile_number": getattr(partner, "mobile", "") or "",
                    "email": email,
                    "observations": "",
                    "internal_observations": "",
                },
            }
        }
        response = self._send_request('PATCH', f"/api/customers/{customer_id}", payload=customer_payload)
        if response.status_code not in (200, 204):
            raise UserError(_("Error updating customer in TOConline: %s") % response.text)

    def get_customer_id(self, tax_number=None, email=None):
        customers = []
        if tax_number and tax_number.isdigit() and len(tax_number) == 9:
            response = self._send_request(
                'GET', f"/api/customers?filter[tax_registration_number]={tax_number}",
            )
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if not customers and email:
            response = self._send_request('GET', f"/api/customers?filter[email]={email}")
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if customers:
            return customers[0]["id"]
        return None

    # -----------------------------------------------------------------
    # D. Product management
    # -----------------------------------------------------------------

    def get_or_create_product(self, product):
        if not product.default_code:
            raise UserError(_("Product code (default_code) is empty."))

        response = self._send_request(
            'GET', f"/api/products?filter[item_code]={product.default_code}",
        )
        if response.status_code == 200:
            products = response.json().get('data', [])
            if products:
                return products[0]["id"]

        if product.list_price is None:
            raise UserError(
                _("The selling price (list_price) of the product %s is empty.") % product.name
            )

        product_payload = {
            "data": {
                "type": "products",
                "attributes": {
                    "type": "Product",
                    "item_code": product.default_code,
                    "item_description": product.name,
                    "sales_price": product.list_price,
                    "sales_price_includes_vat": False,
                },
            }
        }
        response = self._send_request('POST', "/api/products", payload=product_payload)
        if response.status_code in (200, 201):
            data = response.json()
            product_id = data.get("data", {}).get("id")
            if not product_id:
                raise UserError(_("Product created, but ID was not returned: %s") % data)
            return product_id
        else:
            raise UserError(_("Error creating product in TOConline: %s") % response.text)

    # -----------------------------------------------------------------
    # E. Document operations
    # -----------------------------------------------------------------

    def get_document_field_by_number(self, document_no, field_name):
        response = self._send_request(
            'GET', f"/api/v1/commercial_sales_documents?filter[document_no]={document_no}",
        )
        data = response.json()
        if isinstance(data, list):
            documents = data
        elif isinstance(data, dict):
            documents = data.get('data', [])
        else:
            documents = []

        if not documents:
            raise UserError(
                _("Document with number %s not found in TOConline.") % document_no
            )
        return documents[0].get(field_name)

    def get_document_fields_by_number(self, document_no):
        """Fetch a single document by number and return its full data dict.

        Use this instead of calling get_document_field_by_number multiple times
        for the same document to avoid repeated API round-trips.
        """
        response = self._send_request(
            'GET', f"/api/v1/commercial_sales_documents?filter[document_no]={document_no}",
        )
        data = response.json()
        if isinstance(data, list):
            documents = data
        elif isinstance(data, dict):
            documents = data.get('data', [])
        else:
            documents = []

        if not documents:
            raise UserError(
                _("Document with number %s not found in TOConline.") % document_no
            )
        return documents[0]

    def get_document_by_id(self, document_id):
        try:
            response = self._send_request(
                'GET', f"/api/v1/commercial_sales_documents/{document_id}",
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            _logger.error("Connection error for TOC document ID %s: %s", document_id, str(e))
            return None

    def get_last_document_date(self, document_type=None):
        """Return the date of the most recent document in TOConline.
        """
        url = "/api/v1/commercial_sales_documents?sort=-date&page[size]=1"
        if document_type:
            url += f"&filter[document_type]={document_type}"
        try:
            response = self._send_request('GET', url)
            if response.status_code == 200:
                res_data = response.json()
                items = res_data if isinstance(res_data, list) else res_data.get('data', [])
                if items:
                    last_date_str = items[0].get('date')
                    _logger.info(
                        "Last date in TOConline (document_type=%s): %s",
                        document_type or "ANY", last_date_str,
                    )
                    return fields.Date.from_string(last_date_str)
        except Exception as e:
            _logger.error("Failed to validate TOConline chronology: %s", str(e))
        return None

    def is_saft_exported(self, document_id):
        response = self._send_request(
            'GET', f"/api/commercial_sales_documents/{document_id}",
        )
        if response.status_code == 200:
            data = response.json().get("data", {}).get("attributes", {})
            communication_status = data.get("communication_status")
            return communication_status != "unsent"
        else:
            raise UserError(
                _("Error while checking SAFT status in TOConline: %s") % response.text
            )

    def send_document(self, payload):
        response = self._send_request(
            'POST', "/api/v1/commercial_sales_documents", payload=payload,
        )
        return response

    def cancel_document(self, document_id, reason):
        cancel_payload = {
            "data": {
                "type": "commercial_sales_documents",
                "id": str(document_id),
                "attributes": {
                    "status": 4,
                    "voided_reason": reason,
                },
            }
        }
        return self._send_request(
            'PATCH', "/api/commercial_sales_documents", payload=cancel_payload,
        )

    def get_document_lines(self, document_no):
        url = f"/api/v1/commercial_sales_documents?filter[document_no]={document_no}"
        try:
            response = self._send_request('GET', url)
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            if isinstance(data, dict):
                return data
            return None
        except requests.exceptions.RequestException:
            return None

    # -----------------------------------------------------------------
    # F. Tax operations
    # -----------------------------------------------------------------

    def get_taxes(self):
        response = self._send_request('GET', "/api/taxes")
        if response.status_code == 200:
            return response.json().get('data', [])
        else:
            raise UserError(_("Error fetching rates from TOConline: %s") % response.text)

    def get_tax_info(self, percentage, region, tax_list):
        for tax in tax_list:
            tax_attr = tax["attributes"]
            if (
                float(tax_attr["tax_percentage"]) == float(percentage)
                and tax_attr["tax_country_region"] == region
            ):
                return {
                    "code": tax_attr["tax_code"],
                    "percentage": tax_attr["tax_percentage"],
                    "id": tax["id"],
                }
        raise UserError(
            _("No rate was found with %s%% for the region %s.") % (percentage, region)
        )

    def get_tax_exemption_reason_id(self, reason_code):
        response = self._send_request(
            'GET', f"/tax_exemption_reasons?filter[code]={reason_code}",
        )
        if response.status_code != 200:
            raise UserError(
                _("Error searching for exemption reason in TOConline: %s") % response.text
            )
        data = response.json().get("data", [])
        if not data:
            return None
        return data[0]["id"]

    @staticmethod
    def get_tax_region(state_name):
        return {"Madeira": "PT-MA", "Açores": "PT-AC"}.get(state_name, "PT")

    # -----------------------------------------------------------------
    # G. Receipt/payment operations
    # -----------------------------------------------------------------

    def get_receipt(self, receipt_id):
        try:
            response = self._send_request(
                'GET', f"/api/v1/commercial_sales_receipts/{receipt_id}",
            )
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
            return None
        except Exception as e:
            _logger.error("Error fetching receipt %s from TOConline: %s", receipt_id, str(e))
            return None

    def create_receipt(self, payload):
        return self._send_request('POST', "/api/v1/commercial_sales_receipts", payload=payload)

    # -----------------------------------------------------------------
    # H. PDF operations
    # -----------------------------------------------------------------

    def download_and_attach_pdf(self, record, document_id, filename, message=None):
        url_api = f"/api/url_for_print/{document_id}?filter[type]=Document&filter[copies]=1"
        response = self._send_request('GET', url_api)
        if response.status_code != 200:
            raise UserError(_("Failed to get PDF URL from TOConline."))

        try:
            url_data = response.json()["data"]["attributes"]["url"]
            pdf_url = f"{url_data['scheme']}://{url_data['host']}{url_data['path']}"
        except Exception as e:
            raise UserError(_("Error parsing PDF URL response: %s") % str(e))

        pdf_response = requests.get(pdf_url, timeout=TOC_TIMEOUT)
        if pdf_response.status_code != 200:
            raise UserError(_("Failed to download PDF from TOConline."))

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'res_model': record._name,
            'res_id': record.id,
            'type': 'binary',
            'datas': base64.b64encode(pdf_response.content),
            'mimetype': 'application/pdf',
        })

        post_message = message or _("PDF successfully downloaded and attached.")
        record.message_post(
            body=Markup(post_message),
            attachment_ids=[attachment.id],
        )
        return attachment

    # -----------------------------------------------------------------
    # I. VAT exemption
    # -----------------------------------------------------------------

    def fetch_vat_exemption_reasons(self):
        try:
            response = self._send_request('GET', "/api/tax_descriptors")
            if response.status_code == 200:
                data = response.json()
                return data.get('data', [])
            _logger.warning("TOConline API (%s): %s", response.status_code, response.text)
            return []
        except Exception as e:
            _logger.error("Error connecting to TOConline: %s", str(e))
            return []

    # -----------------------------------------------------------------
    # J. AT communication
    # -----------------------------------------------------------------

    def communicate_to_at(self, record, document_id, document_type):
        at_user = self.company.toc_at_username
        at_pass = self.company.toc_at_password

        if not at_user or not at_pass:
            record.message_post(body=_("AT credentials missing, skipping communication"))
            return True

        payload_at = {
            "data": {
                "type": "send_document_at_webservice",
                "id": document_id,
                "attributes": {
                    "document_type": document_type,
                    "entity_username": at_user,
                    "entity_password": base64.b64encode(at_pass.encode("utf-8")).decode("utf-8"),
                },
            }
        }
        try:
            response = self._send_request(
                'POST', "/api/send_document_at_webservice", payload=payload_at,
            )
            if response.status_code == 200:
                at_data = response.json().get("data", {}).get("attributes", {})
                communication_code = at_data.get("communication_code")
                record.toc_communication_code = communication_code
                record.message_post(body=_("AT Communication Code: %s") % communication_code)
                return True
            else:
                record.message_post(body=_("AT communication fail: %s") % response.status_code)
        except Exception as e:
            record.message_post(body=_("AT communication fail: %s") % e)
        return True
