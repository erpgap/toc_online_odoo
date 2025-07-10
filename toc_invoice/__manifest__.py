{
    'name': 'Portugal TOCOnline Integration',
    'version': '1.0.1',
    'description': 'Portuguese certified invoices using TOCOnline.',
    'summary': 'Portuguese certified invoices using TOCOnline.',
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
        'data/ir_cron.xml',
        'data/ir_cron_sync_credit_note.xml',
        'data/ir_cron_sync_invoice_toc.xml',
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
