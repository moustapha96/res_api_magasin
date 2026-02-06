# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json

# Clés booléennes (config_parameter -> type)
BOOLEAN_KEYS = {
    'rental.auto_generate_invoices',
    'rental.auto_send_invoices',
    'rental.send_email',
    'rental.send_sms',
    'rental.send_whatsapp',
    'rental.auto_send_reminders',
    'rental.enable_wave',
    'rental.enable_orange_money',
    'rental.enable_stripe',
    'rental.allow_partial_payment',
    'rental.late_fee_enabled',
}

# Clés entières
INTEGER_KEYS = {
    'rental.invoice_days_before',
    'rental.reminder_frequency_days',
    'rental.max_reminders',
    'rental.grace_period_days',
}

# Clés décimales
FLOAT_KEYS = {
    'rental.late_fee_percentage',
}

# Clés Many2one (config stocke l'ID) -> on retourne id + display_name si dispo
MANY2ONE_KEYS = {
    'rental.email_template_id': 'mail.template',
    'rental.reminder_email_template_id': 'mail.template',
    'rental.income_account_id': 'account.account',
    'rental.deposit_account_id': 'account.account',
    'rental.payment_journal_id': 'account.journal',
}

# Clés sensibles : ne pas exposer la valeur en clair dans l'API
SENSITIVE_KEYS = {
    'rental.whatsapp_api_token',
}


def _parse_config_value(key, value):
    """Convertit une valeur ir.config_parameter (string) vers le type attendu."""
    if value is None or value == '':
        if key in BOOLEAN_KEYS:
            return False
        if key in INTEGER_KEYS:
            return 0
        if key in FLOAT_KEYS:
            return 0.0
        return None
    if key in BOOLEAN_KEYS:
        return value in ('True', 'true', '1', True)
    if key in INTEGER_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if key in FLOAT_KEYS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    return value


class RentalConfigController(http.Controller):

    @http.route('/api/rental/config', type="http", auth="none", methods=["GET"], cors="*", csrf=False)
    def get_rental_config(self, **kwargs):
        """
        Récupère les paramètres de configuration pour la gestion des locations
        (alignés sur res.config.settings / ResConfigSettings).
        Retourne un dictionnaire JSON avec les valeurs actuelles.
        Les secrets (tokens, clés API) sont masqués.
        """
        try:
            config_params = request.env['ir.config_parameter'].sudo()
            config_values = {}

            # 1) Paramètres scalaires (bool, int, float, char, selection)
            all_scalar_keys = (
                list(BOOLEAN_KEYS) + list(INTEGER_KEYS) + list(FLOAT_KEYS) + [
                    'rental.sms_provider',
                ]
            )
            for key in all_scalar_keys:
                raw = config_params.get_param(key)
               
                if key in BOOLEAN_KEYS or key in INTEGER_KEYS or key in FLOAT_KEYS:
                    config_values[key] = _parse_config_value(key, raw)
                else:
                    config_values[key] = raw or None


            return request.make_response(
                json.dumps(config_values, default=str),
                headers=[('Content-Type', 'application/json')]
            )

        except Exception as e:
            return request.make_response(
                json.dumps({'error': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=500
            )
