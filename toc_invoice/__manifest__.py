{
    'name': 'TOC',
    'version': '1.0.0',
    'description': 'comunicação API ',
    'summary': 'omunicação API',
    'category': 'Accounting/Accounting',
    'depends': ['base', 'web', 'contacts', 'product', 'account' , 'l10n_pt_vat' ],
    'data': [
        'security/ir.model.access.csv',
        'views/toc_invoice.xml',
        'views/res_config_settings.xml',
        'views/res_company_views.xml',
        'views/res_partner_views.xml',
        'wizard/toc_account_move_reversal.xml',
        'views/toc_credit_note.xml',
        'views/toc_invoice_list.xml',
        'data/ir_cron.xml'


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