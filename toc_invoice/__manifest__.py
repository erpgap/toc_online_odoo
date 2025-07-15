{
    'name': 'Portugal TOCOnline Integration',
    'version': '1.0.0',
    'description': 'Integrates Odoo with TOConline for certified invoicing in Portugal: create, cancel, and manage customer invoices and credit notes; register payments; download invoices from TOConline into Odoo; and send official TOConline invoices by email.',
    'summary': 'Portuguese certified invoices using TOCOnline',
    'category': 'Accounting/Accounting',
    "license": "AGPL-3",
    'depends': ['base', 'web', 'contacts', 'product', 'account' , 'l10n_pt_vat' ],
    'data': [
        'security/ir.model.access.csv',
        'views/toc_invoice.xml',
        'views/res_config_settings.xml',
        'views/account_journal_view.xml',
        'views/res_company_views.xml',
        'views/res_partner_views.xml',
        'wizard/toc_account_move_reversal.xml',
        'views/toc_credit_note.xml',
        'views/toc_invoice_list.xml',
        'wizard/toc_cancel_invoice.xml',
    ],
    'assets':{
        'web.assets_backend':[
            'toc_invoice/static/src/css/style.css',
        ]
    },

    'images': [

    ],
    'licence': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}