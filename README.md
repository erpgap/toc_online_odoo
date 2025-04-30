Portugal TOConline Integration
=============================== 

This project aims to integrate the ERP Odoo with the TOConline system, ensuring compliance with Portuguese tax regulations.

The integration allows the export and synchronization of tax data, such as invoices, credit notes and payments, ensuring efficient communication with the Tax Authority (AT) through the TOConline API.


📌 Objectives
=====================
Technical analysis of the integration requirements between Odoo and TOConline.
Development of modules and features in Odoo to enable data export and synchronization.
Implementation of TOConline API communication.
Validation of fiscal compliance with the AT.
Testing and documentation to ensure reliability and maintainability.

⚙️ Features
======================
Create invoices in TOConline from Odoo.
Bidirectional payment synchronization (Odoo → TOConline / TOConline → Odoo).
Prevent client duplication by using unique references.
Support for multiple currencies (USD, EUR, GBP, ...).
Create Credit Notes in TOConline from Odoo.
Bidirectional synchronization of Credit Note payments.
Handle document cancellations.
Enforce date and sequence restrictions (e.g., no retroactive invoices or refunds).
