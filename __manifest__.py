# -*- coding: utf-8 -*-
{
    'name': 'API Gestion Locative d\'Immeuble',
    'version': '18.0.1.0',
    'author': 'Al Hussein Khouma',
    'license': 'LGPL-3',
    'category': 'Immobilier',
    'summary': 'API RESTful avancée pour la gestion locative d\'immeubles avec schémas de réponse personnalisables.',
    'description': """
        Cette application fournit un accès RESTful avancé aux ressources Odoo, avec des schémas de réponse prédéfinis et personnalisables.
        Elle permet une intégration facile avec d'autres systèmes via des endpoints, des méthodes d'appel, et des webhooks.
        Elle supporte également OpenAPI, OAuth, et Swagger pour une documentation et une sécurité optimales.
    """,
    'website': 'https://votre-site-web.com',
    'depends': [
        'base',
        'web',
        'account',
        'contacts',
    ],
    'external_dependencies': {
        'python': ['simplejson'],
    },
    'data': [
        'security/ir.model.access.csv',
        'data/ir_configparameter_data.xml',
        'views/rental_contract_views.xml',
        'views/rental_building_views.xml',
        'views/rental_property_views.xml',
        'views/rental_payment_schedule_views.xml',
        'views/gestion_magasin_config_views.xml',
        'views/account_move_rental_payment_views.xml',
        'views/rental_menu.xml',
        'views/res_partner_view.xml',

    ],
    'images': [
        'static/description/icon.png',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
