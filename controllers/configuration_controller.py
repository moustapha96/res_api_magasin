# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, Response
import json

class RentalConfigController(http.Controller):

    @http.route('/api/rental/config', type="http", auth="none", methods=["GET"], cors="*", csrf=False)
    def get_rental_config(self, **kwargs):
        """
        Récupère les paramètres de configuration pour la gestion des locations.
        Retourne un dictionnaire JSON avec les valeurs actuelles.
        """
        try:
            # Récupérer les paramètres depuis IrConfigParameter
            config_params = request.env['ir.config_parameter'].sudo()
            # Liste des clés de configuration à récupérer
            config_keys = [
                'rental.auto_generate_invoices',
                'rental.invoice_days_before',
                'rental.auto_send_invoices',
                'rental.send_email',
                'rental.send_sms',
                'rental.send_whatsapp',
                'rental.auto_send_reminders',
                'rental.reminder_frequency_days',
                'rental.max_reminders',
                'rental.enable_wave',
                'rental.enable_orange_money',
                'rental.enable_stripe',
                'rental.allow_partial_payment',
                'rental.late_fee_enabled',
                'rental.late_fee_percentage',
                'rental.grace_period_days',
            ]

            # Récupérer les valeurs
            config_values = {}
            for key in config_keys:
                value = config_params.get_param(key, default=False)
                # Convertir les valeurs en type approprié (booléen, entier, etc.)
                if key in ['rental.auto_generate_invoices', 'rental.auto_send_invoices', 'rental.send_email', 'rental.send_sms', 'rental.send_whatsapp', 'rental.auto_send_reminders', 'rental.enable_wave', 'rental.enable_orange_money', 'rental.enable_stripe', 'rental.allow_partial_payment', 'rental.late_fee_enabled']:
                    value = value == 'True' or value is True
                elif key in ['rental.invoice_days_before', 'rental.reminder_frequency_days', 'rental.max_reminders', 'rental.grace_period_days']:
                    value = int(value) if value else 0
                elif key in ['rental.late_fee_percentage']:
                    value = float(value) if value else 0.0
                config_values[key] = value

            # Retourner les valeurs au format JSON
            return request.make_response(
                json.dumps(config_values),
                headers=[('Content-Type', 'application/json')]
            )

        except Exception as e:
            return request.make_response(
                json.dumps({'error': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=500
            )
