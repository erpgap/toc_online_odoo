# Portugal TOConline Integration

This project aims to integrate the Odoo ERP with the TOConline system, ensuring compliance with Portuguese tax regulations.

The integration allows the export and synchronization of tax data **from Odoo to TOConline**, such as invoices, credit notes, and payments, ensuring efficient communication with the Tax Authority (AT) through the TOConline API.

## Description

Integrates Odoo with TOConline for certified invoicing in Portugal: create, cancel, and manage customer invoices and credit notes; register payments; download invoices from TOConline into Odoo; and send official TOConline invoices by email.

## Objectives

- Technical analysis of the integration requirements between Odoo and TOConline.
- Development of modules and features in Odoo to enable data export and synchronization.
- Implementation of TOConline API communication.
- Validation of fiscal compliance with the AT.
- Testing and documentation to ensure reliability and maintainability.

## Features

- Create invoices in TOConline from Odoo.
- Payment synchronization from Odoo to TOConline.
- Prevent client duplication by using unique references.
- Support for multiple currencies (USD, EUR, GBP, ...).
- Create Credit Notes in TOConline from Odoo.
- Payment synchronization of Credit Notes from Odoo to TOConline.
- Handle document cancellations.
- Enforce date and sequence restrictions (e.g., no retroactive invoices or refunds).

## Extra information for using the module

This module allows communication between Odoo and the TOConline platform, which is Portuguese, therefore containing only Portuguese VAT values.  
Depending on your company's location and operations, not all VAT rates may be valid for use. For example, a company based in mainland Portugal should not use Azores or Madeira VAT rates.  
Please ensure that your company's VAT settings in Odoo reflect the correct region to avoid compliance issues when communicating with TOConline.

---

## Installation and Configuration

### Installation

1. Copy or clone the module into your Odoo custom addons folder:  

```bash
git clone https://github.com/erpgap/toc_online_odoo.git
```
2. Update the apps list in Odoo and install the TOConline Integration module.

### Configuration

After installation, go to:

Fill in the following information:

- **TOConline Client ID**
- **TOConline Client Secret**
- **TOConline Company ID**

Save the configuration and authenticate to enable the connection.

---

## How to Obtain TOConline API Credentials

To use this integration, you must obtain your company's credentials directly from the TOConline platform.

Steps to obtain your credentials:

1. Access your TOConline account:  
   https://app.toconline.pt

2. In the left menu, go to **Configurações Empresa**.

3. Open the **Dados da API** section.

4. Copy the following information:
   - Client ID
   - Client Secret (Generated automatically — keep it secure)
   - Company ID 

5. Enter this information in the TOConline Configuration section in Odoo.

⚠️ **Important:** The Client Secret is confidential and must not be shared.  
Without these credentials, Odoo will not be able to connect with TOConline.