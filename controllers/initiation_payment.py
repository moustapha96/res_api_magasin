# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json
import logging
import re

_logger = logging.getLogger(__name__)

class PaymentController(http.Controller):
    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _json(self, data, status=200):
        return request.make_response(
            json.dumps(data, ensure_ascii=False, default=str),
            headers=[('Content-Type', 'application/json')],
            status=status
        )

    def _make_response(self, data, status=200):
        # compat avec ton code existant
        if isinstance(data, (dict, list)):
            return self._json(data, status=status)
        return request.make_response(str(data), status=status)

    def _normalize_phone(self, raw, default_cc='221'):
        s = (raw or '').strip().replace(' ', '')
        if not s:
            return None
        # enlève tout sauf + et digits
        s = re.sub(r'[^+\d]', '', s)
        if s.startswith('+'):
            return s
        # Numéros SN courants : 77/78/76/70/75 etc.
        if len(s) == 9 and s[0] in '76570':  # ex: 778112233
            return f'+{default_cc}{s}'
        if len(s) == 12 and s.startswith(default_cc):  # ex: 221778112233
            return f'+{s}'
        if len(s) == 8:  # ex: 78112233 -> suppose 7x/76/70/75, on préfixe 0
            return f'+{default_cc}0{s}'
        return f'+{default_cc}{s}'

    def _invoice_amounts(self, move):
        # On paie le restant dû si dispo, sinon total
        amount = float(move.amount_residual) if move.amount_residual else float(move.amount_total)
        currency = (move.currency_id and move.currency_id.name) or (move.company_currency_id and move.company_currency_id.name) or 'XOF'
        return amount, currency

    def _serialize_invoice_light(self, move):
        """Résumé utile côté front (si besoin)."""
        lines = [{
            'name': l.name,
            'quantity': l.quantity,
            'price_unit': l.price_unit,
            'price_subtotal': l.price_subtotal,
            'price_total': l.price_total,
        } for l in move.invoice_line_ids]
        return {
            'id': move.id,
            'name': move.name,
            'transaction_id': move.transaction_id,
            'partner_id': move.partner_id.id,
            'partner_name': move.partner_id.name,
            'amount_total': float(move.amount_total),
            'amount_residual': float(move.amount_residual),
            'currency': (move.currency_id and move.currency_id.name) or 'XOF',
            'state': move.state,
            'lines': lines,
        }

    # ---------------------------------------------------------------------
    # Cœurs métiers réutilisables (pas des routes HTTP)
    # ---------------------------------------------------------------------
    def _initiate_orange_core(self, payload: dict):
        """Reprend la logique de initiate_orange_payment mais en pur Python."""
        try:
            # === Validation minimale
            required = ['transaction_id', 'facture_id', 'partner_id', 'phoneNumber', 'amount']
            if not all(payload.get(k) for k in required):
                return self._make_response({'message': f"Missing required fields: {', '.join(required)}"}, 400)

            config = request.env['orange.money.config'].sudo().search([('is_active', '=', True)], limit=1)
            if not config:
                return self._make_response({'error': 'Orange Money configuration not found', 'success': False}, 400)

            account_move = request.env['account.move'].sudo().browse(int(payload['facture_id']))
            partner = request.env['res.partner'].sudo().browse(int(payload['partner_id']))
            if not account_move:
                return self._make_response({'message': "La facture n'existe pas"}, 400)
            if not partner:
                return self._make_response({'message': "Le partenaire n'existe pas"}, 400)

            # idempotence
            existing_tx = request.env['orange.money.transaction'].sudo().search([('transaction_id', '=', payload['transaction_id'])], limit=1)
            if existing_tx:
                return self._make_response({
                    'success': True,
                    'transaction_id': existing_tx.transaction_id,
                    'pay_token': existing_tx.pay_token,
                    'payment_url': existing_tx.payment_url,
                    'status': existing_tx.status or 'INITIATED',
                    'account_move_id': existing_tx.account_move_id.id if existing_tx.account_move_id else False,
                    'partner_id': existing_tx.partner_id.id,
                    'reference': existing_tx.reference,
                    'success_url': payload.get('success_url'),
                    'deep_link': existing_tx.deep_link,
                    'deep_link_om': existing_tx.deep_link_om,
                    'deep_link_maxit': existing_tx.deep_link_maxit,
                    'short_link': existing_tx.short_link,
                    'qr_code_base64': existing_tx.qr_code_base64,
                    'qr_id': existing_tx.qr_id,
                    'validity_seconds': existing_tx.validity_seconds,
                    'valid_from': existing_tx.valid_from.isoformat() if existing_tx.valid_from else None,
                    'valid_until': existing_tx.valid_until.isoformat() if existing_tx.valid_until else None,
                    'amount': float(existing_tx.amount) if existing_tx.amount else None,
                    'currency': existing_tx.currency or (existing_tx.account_move_id.currency_id and existing_tx.account_move_id.currency_id.name) or 'XOF',
                    'existe': True
                }, 200)

            # créer l'ordre via la config
            created = config.create_payment_invoice(
                amount=payload['amount'],
                currency=payload.get('currency', 'XOF'),
                account_move_id=account_move.id,
                transaction_id=payload['transaction_id'],
                customer_msisdn=payload['phoneNumber'],
                description=payload.get('description', 'Payment via Orange Money'),
                reference=payload.get('reference'),
                success_url=payload.get('success_url') or f"https://portail.toubasandaga.sn/om-paiement?transaction={payload['transaction_id']}",
                cancel_url=payload.get('cancel_url') or f"https://portail.toubasandaga.sn/facture-magasin?transaction={account_move.transaction_id}",
            )

            if not created or not created.get('success'):
                return self._make_response({'error': (created or {}).get('message', 'Failed to create Orange Money payment order')}, 400)

            orange_transaction = request.env['orange.money.transaction'].sudo().create({
                'success_url': payload.get('success_url'),
                'cancel_url': payload.get('cancel_url'),
                'pay_token': created.get('pay_token'),
                'transaction_id': payload['transaction_id'],
                'amount': payload['amount'],
                'currency': payload.get('currency', 'XOF'),
                'status': 'INITIATED',
                'customer_msisdn': payload['phoneNumber'],
                'merchant_code': config.merchant_code,
                'reference': payload.get('reference'),
                'description': payload.get('description'),
                'payment_url': created.get('payment_url'),
                'qr_code_url': created.get('deep_link'),
                'qr_code_base64': created.get('qr_code_base64'),
                'qr_id': created.get('qr_id'),
                'deep_link': created.get('deep_link'),
                'deep_link_om': created.get('deep_link_om'),
                'deep_link_maxit': created.get('deep_link_maxit'),
                'short_link': created.get('short_link'),
                'validity_seconds': created.get('validity_seconds'),
                'valid_from': created.get('valid_from'),
                'valid_until': created.get('valid_until'),
                'orange_response': created.get('orange_response'),
                'metadata': json.dumps(payload.get('metadata') or {}),
                'account_move_id': account_move.id,
                'partner_id': partner.id,
                'orange_id': created.get('qr_id'),
                'callback_url': created.get('callback_url'),
            })

            return self._make_response({
                'success': True,
                'gateway': 'orange',
                'transaction_id': orange_transaction.transaction_id,
                'payment_url': orange_transaction.payment_url,
                'pay_token': orange_transaction.pay_token,
                'status': orange_transaction.status or 'INITIATED',
                'account_move_id': orange_transaction.account_move_id.id if orange_transaction.account_move_id else False,
                'partner_id': orange_transaction.partner_id.id,
                'reference': orange_transaction.reference,
                'deep_link': orange_transaction.deep_link,
                'deep_link_om': orange_transaction.deep_link_om,
                'deep_link_maxit': orange_transaction.deep_link_maxit,
                'short_link': orange_transaction.short_link,
                'qr_code_base64': orange_transaction.qr_code_base64,
                'qr_id': orange_transaction.qr_id,
                'validity_seconds': orange_transaction.validity_seconds,
                'valid_from': orange_transaction.valid_from.isoformat() if orange_transaction.valid_from else None,
                'valid_until': orange_transaction.valid_until.isoformat() if orange_transaction.valid_until else None,
            }, 200)

        except Exception as e:
            _logger.exception("Orange core error")
            return self._make_response({'error': str(e)}, 400)

    def _initiate_wave_core(self, payload: dict):
        """Reprend la logique de initiate_wave_payment mais en pur Python (sans POST HTTP)."""
        try:
            required = ['transaction_id', 'facture_id', 'partner_id', 'phoneNumber', 'amount']
            if not all(payload.get(k) for k in required):
                return self._make_response({'message': f"Missing required fields: {', '.join(required)}"}, 400)

            config = request.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
            if not config:
                return self._make_response({'error': 'Wave configuration not found', 'success': False}, 400)

            account_move = request.env['account.move'].sudo().browse(int(payload['facture_id']))
            partner = request.env['res.partner'].sudo().browse(int(payload['partner_id']))
            if not account_move:
                return self._make_response({'message': "La commande/facture n'existe pas"}, 400)
            if not partner:
                return self._make_response({'message': "Le partner n'existe pas"}, 400)

            existing_tx = request.env['wave.transaction'].sudo().search([('transaction_id', '=', payload['transaction_id'])], limit=1)
            if existing_tx:
                return self._make_response({
                    'success': True,
                    'gateway': 'wave',
                    'transaction_id': existing_tx.transaction_id,
                    'invoice': getattr(existing_tx.account_move_id, 'get_invoice_details', lambda: {})(),
                    'wave_id': existing_tx.wave_id,
                    'session_id': existing_tx.wave_id,
                    'payment_url': existing_tx.payment_link_url,
                    'status': existing_tx.status or 'pending',
                    'account_move_id': existing_tx.account_move_id.id,
                    'partner_id': existing_tx.partner_id.id,
                    'reference': existing_tx.reference,
                    'existe': True
                }, 200)

            # Appel API Wave checkout sessions
            import requests   # local import pour éviter erreurs si non installé ailleurs
            payload_api = {
                "amount": payload['amount'],
                "currency": payload.get('currency', 'XOF'),
                "success_url": payload.get('success_url') or f"https://portail.toubasandaga.sn/wave-paiement?transaction={payload['transaction_id']}",
                "error_url": config.callback_url
            }
            headers = {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post("https://api.wave.com/v1/checkout/sessions", json=payload_api, headers=headers, timeout=30)
            if resp.status_code not in (200, 201):
                _logger.error(f"Wave API Error: {resp.status_code} - {resp.text}")
                return self._make_response(resp.text, 400)

            data = resp.json()
            wave_tx = request.env['wave.transaction'].sudo().create({
                'wave_id': data.get('id'),
                'transaction_id': payload['transaction_id'],
                'amount': payload['amount'],
                'currency': payload.get('currency', 'XOF'),
                'status': 'pending',
                'phone': payload.get('phoneNumber'),
                'reference': payload.get('reference'),
                'description': payload.get('description', 'Payment via Wave'),
                'payment_link_url': data.get('wave_launch_url') or data.get('checkout_url'),
                'wave_response': json.dumps(data),
                'account_move_id': account_move.id,
                'partner_id': partner.id,
                'checkout_status': data.get('checkout_status'),
                'payment_status': data.get('payment_status'),
            })

            return self._make_response({
                'success': True,
                'gateway': 'wave',
                'transaction_id': wave_tx.transaction_id,
                'wave_id': data.get('id'),
                'session_id': data.get('id'),
                'payment_url': data.get('wave_launch_url') or data.get('checkout_url'),
                'status': 'pending',
                'account_move_id': wave_tx.account_move_id.id,
                'partner_id': wave_tx.partner_id.id,
                'reference': payload.get('reference'),
                'checkout_status': data.get('checkout_status'),
                'payment_status': data.get('payment_status'),
            }, 200)

        except Exception as e:
            _logger.exception("Wave core error")
            return self._make_response({'error': str(e)}, 400)

    # ---------------------------------------------------------------------
    # Route facture → init paiement
    # ---------------------------------------------------------------------
    @http.route("/facture-paiement/<string:transaction>/type/<string:type_paiement>", type="http", auth="public", methods=["GET"], csrf=False, cors="*")
    def api_invoice_by_transaction(self, transaction, type_paiement, **kw):
        """
        GET /facture-paiement/<transaction>/type/<type_paiement>
        1) Cherche la facture par transaction_id
        2) Prépare le payload pour OM/Wave
        3) Lance l'initiation et renvoie la réponse unifiée

        Réponse succès (exemples) :
        - Orange:
          {"success": true, "gateway": "orange", "transaction_id": "...", "payment_url": "...", "deep_link": "...", ...}
        - Wave:
          {"success": true, "gateway": "wave", "transaction_id": "...", "payment_url": "...", "session_id": "...", ...}
        """
        try:
            tx = (transaction or '').strip()
            if not tx:
                return self._json({"error": "missing_transaction", "message": "Paramètre 'transaction' requis."}, status=400)

            Move = request.env["account.move"].sudo()
            move = Move.search([("transaction_id", "=", tx), ("move_type", "in", ("out_invoice", "out_refund"))], limit=1)
            if not move:
                return self._json({"error": "not_found", "message": "Aucune facture pour cette transaction."}, status=404)

            # Montants & devise
            amount, currency = self._invoice_amounts(move)

            # Partner & téléphone
            partner = move.partner_id
            raw_phone = partner.whatsapp_number or partner.phone
            phone = self._normalize_phone(raw_phone) if raw_phone else None

            # Référence & description
            reference = f"INV-{move.name}"
            description = f"Règlement facture {move.name}"

            # URLs succès génériques (le front peut les ignorer si besoin)
            success_url_om = f"https://portail.toubasandaga.sn/om-paiement?transaction={tx}"
            success_url_wave = f"https://portail.toubasandaga.sn/wave-paiement?transaction={tx}"

            # Payload commun
            base_payload = {
                "transaction_id": tx,
                "partner_id": partner.id,
                "phoneNumber": phone,
                "amount": amount,
                "currency": currency,
                "description": description,
                "reference": reference,
                "facture_id": move.id,
                "metadata": {
                    "account_move_transaction_id": move.transaction_id,
                    "account_move_name": move.name,
                },
            }

            # Sélection passerelle
            gateway = (type_paiement or '').strip().lower()
            if gateway in ('om', 'orange', 'orange_money', 'orangemoney'):
                payload = dict(base_payload)
                payload['success_url'] = success_url_om
                payload['cancel_url'] = f"https://portail.toubasandaga.sn/facture-magasin?transaction={move.transaction_id}"

                # garde-fou téléphone
                if not payload.get('phoneNumber'):
                    return self._make_response({'error': "Aucun numéro client pour Orange Money"}, 400)

                return self._initiate_orange_core(payload)

            elif gateway in ('wave',):
                payload = dict(base_payload)
                payload['success_url'] = success_url_wave

                if not payload.get('phoneNumber'):
                    # Wave checkout n'exige pas forcément le MSISDN, mais on garde la cohérence
                    payload['phoneNumber'] = None

                return self._initiate_wave_core(payload)

            else:
                return self._json({"error": "unsupported_gateway", "message": "type_paiement doit être 'om' ou 'wave'."}, status=400)

        except Exception as e:
            _logger.exception("Error in api_invoice_by_transaction")
            return self._json({"error": "server_error", "message": str(e)}, status=500)

    # ---------------------------------------------------------------------
    # (Optionnel) Routes existantes: wrap vers les cœurs
    # ---------------------------------------------------------------------
    # @http.route('/api/payment/orange/initiate', type='http', auth='public', cors='*', methods=['POST'], csrf=False)
    # def initiate_orange_payment(self, **kwargs):
    #     try:
    #         data = json.loads(request.httprequest.data or '{}')
    #         return self._initiate_orange_core(data)
    #     except Exception as e:
    #         _logger.exception("initiate_orange_payment error")
    #         return self._make_response({'error': str(e)}, 400)


    # @http.route('/api/payment/wave/initiate', type='http', auth='public', cors='*', methods=['POST'], csrf=False)
    # def initiate_wave_payment(self, **kwargs):
    #     try:
    #         data = json.loads(request.httprequest.data or '{}')
    #         return self._initiate_wave_core(data)
    #     except Exception as e:
    #         _logger.exception("initiate_wave_payment error")
    #         return self._make_response({'error': str(e)}, 400)
