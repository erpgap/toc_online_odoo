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
