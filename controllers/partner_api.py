# -*- coding: utf-8 -*-
# controllers/partner_billing_api.py

import json
import logging
from datetime import datetime

from odoo import http, fields
from odoo.http import request
import werkzeug

_logger = logging.getLogger(__name__)

# =========================
# Helpers génériques
# =========================

def _json(data=None, status=200):
    if data is None:
        data = {}
    return werkzeug.wrappers.Response(
        status=status,
        content_type='application/json; charset=utf-8',
        headers=[('Cache-Control', 'no-store'), ('Pragma', 'no-cache')],
        response=json.dumps(data, ensure_ascii=False, default=str),
    )

def _json_message(message, status=200):
    return _json({"message": message}, status=status)

def _parse_body():
    try:
        return json.loads(request.httprequest.data or b"{}")
    except Exception:
        return None

def _parse_args():
    # pour les routes GET à querystring
    return request.httprequest.args.to_dict()

def _require_admin_env():
    """Assure un env sudo non-public (ex. depuis auth='none')."""
    user = request.env['res.users'].sudo().browse(request.env.uid)
    if not user or user._is_public():
        admin_user = request.env.ref('base.user_admin')
        request.env = request.env(user=admin_user.id)

def _mask_phone(p):
    """Masque un numéro (retour '77****34' si possible)."""
    try:
        s = (p or '').strip().replace(' ', '')
        if s.startswith('+'):
            s = s[1:]
        if s.startswith('00221'):
            s = s[5:]
        elif s.startswith('221'):
            s = s[3:]
        return f"{s[:2]}****{s[-2:]}" if len(s) >= 4 else '****'
    except Exception:
        return '****'

def _money(n):
    try:
        return float(n or 0.0)
    except Exception:
        return 0.0


# ================
# Payload builders
# ================

def _property_payload(prop):
    """Sérialisation minimale d'un rental.property"""
    if not prop:
        return None
    return {
        "id": prop.id,
        "name": prop.name,
        "type": prop.property_type,
        "status": prop.status,
        "monthly_rent": _money(prop.monthly_rent),
        "currency": prop.currency_id.name if prop.currency_id else None,
        "building_id": prop.building_id.id if prop.building_id else None,
        "building_name": prop.building_id.name if prop.building_id else None,
        "surface_area": prop.surface_area,
        "floor": prop.floor,
        "address": prop.address,
        "unpaid_total": _money(getattr(prop, 'total_unpaid_invoices', 0.0)),
    }

def _contract_payload(contract, with_counts=True):
    """Sérialisation minimale d'un rental.contract"""
    if not contract:
        return None
    data = {
        "id": contract.id,
        "name": contract.name,
        "state": contract.state,                      # draft|active|expired|terminated
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "duration_months": getattr(contract, 'duration_months', 0),
        "monthly_rent": _money(contract.monthly_rent),
        "currency": contract.currency_id.name if contract.currency_id else None,
        "payment_day": contract.payment_day,
        "payment_frequency": contract.payment_frequency,
        "tenant_id": contract.tenant_id.id if contract.tenant_id else None,
        "tenant_name": contract.tenant_id.name if contract.tenant_id else None,
        "property": _property_payload(contract.property_id),
    }
    if with_counts:
        data.update({
            "invoice_count": getattr(contract, 'invoice_count', 0),
            "paid_invoice_count": getattr(contract, 'paid_invoice_count', 0),
            "unpaid_invoice_count": getattr(contract, 'unpaid_invoice_count', 0),
            "total_unpaid": _money(getattr(contract, 'total_unpaid', 0.0)),
        })
    return data

def _magasin_payload(m):
    return {
        'id': m.id,
        'name': m.name,
        'code': m.code,
        'partner_id': m.partner_id.id if m.partner_id else None,
        'company_id': m.company_id.id if m.company_id else None,
        'active': m.active,
        'email': m.email,
        'phone': m.phone,
        'city': m.city,
        'adress': m.adress,
        'latitude': m.latitude,
        'longitude': m.longitude,
        'opening_hours': m.opening_hours,
        'is_default': m.is_default,
        'logo': bool(getattr(m, 'logo', False)),
        'logo_filename': getattr(m, 'logo_filename', None),
    }

def _partner_payload(partner, with_magasins=True):
    """Réponse Partner enrichie avec les infos locatives."""
    payload = {
        'id': partner.id,
        'name': partner.name,
        'email': partner.email,
        'partner_id': partner.id,
        'company_id': partner.company_id.id if partner.company_id else None,
        'company_name': partner.company_id.name if partner.company_id else None,
        'partner_city': partner.city,
        'partner_phone': partner.phone,
        'country_id': partner.country_id.id or None,
        'country_name': partner.country_id.name or None,
        'country_code': partner.country_id.code if partner.country_id else None,
        'country_phone_code': partner.country_id.phone_code if partner.country_id else None,
        'is_verified': getattr(partner, 'is_verified', False) or getattr(partner, 'otp_verified', False),
        'avatar': getattr(partner, 'avatar', None) or None,
        'image_1920': partner.image_1920.decode('utf-8') if partner.image_1920 else None,
        'function': partner.function or "",
        'role': getattr(partner, 'role', None),
        'parent_id': partner.parent_id.id if partner.parent_id else None,
    }

    # Bloc locatif
    try:
        current_props = []
        if hasattr(partner, 'current_properties'):
            for p in partner.current_properties:
                current_props.append(_property_payload(p))

        payload['rental'] = {
            "is_tenant": bool(getattr(partner, 'is_tenant', False)),
            "preferred_payment_method": getattr(partner, 'preferred_payment_method', None),
            "whatsapp_number": getattr(partner, 'whatsapp_number', None),
            "active_contract_count": getattr(partner, 'active_contract_count', 0),
            "total_contract_count": getattr(partner, 'total_contract_count', 0),
            "current_properties": current_props,
            "unpaid_invoice_count": getattr(partner, 'unpaid_invoice_count', 0),
            "total_unpaid_rent": _money(getattr(partner, 'total_unpaid_rent', 0.0)),
        }
    except Exception:
        payload['rental'] = {
            "is_tenant": False,
            "preferred_payment_method": None,
            "whatsapp_number": None,
            "active_contract_count": 0,
            "total_contract_count": 0,
            "current_properties": [],
            "unpaid_invoice_count": 0,
            "total_unpaid_rent": 0.0,
        }

    if with_magasins and hasattr(partner, 'magasin_ids'):
        payload['magasins'] = [_magasin_payload(m) for m in partner.magasin_ids]

    return payload

def _invoice_line_payload(line):
    return {
        'id': line.id,
        'description': line.name,
        'quantity': line.quantity,
        'unit_price': line.price_unit,
        'total': line.price_subtotal,
        'account': line.account_id.name if line.account_id else None,
        'product_id': line.product_id.id if line.product_id else None,
        'product_name': line.product_id.display_name if line.product_id else None,
        'taxes': [t.name for t in line.tax_ids],
    }

def _payment_basic_payload(pay):
    return {
        'id': pay.id,
        'amount': _money(pay.amount),
        'currency': (pay.currency_id.name if pay.currency_id
                     else (pay.company_id.currency_id.name if pay.company_id else None)),
        'paid_at': pay.date or pay.payment_date,
        'method': (pay.payment_method_line_id.name if pay.payment_method_line_id
                   else (pay.payment_method_id.name if hasattr(pay, 'payment_method_id') and pay.payment_method_id else None)),
        'reference': pay.ref or pay.communication or pay.name,
        'state': pay.state,        # posted / draft / cancelled
        'status': 'posted' if pay.state == 'posted' else pay.state,
    }

def _payment_with_invoices_payload(pay):
    data = _payment_basic_payload(pay)
    try:
        invoice_moves = set()
        for line in pay.move_id.line_ids:
            for m in line.matched_debit_ids:
                if m.debit_move_id and m.debit_move_id.move_id.move_type in ('out_invoice', 'out_refund'):
                    invoice_moves.add(m.debit_move_id.move_id)
            for m in line.matched_credit_ids:
                if m.credit_move_id and m.credit_move_id.move_id.move_type in ('out_invoice', 'out_refund'):
                    invoice_moves.add(m.credit_move_id.move_id)
        data['invoice_ids'] = [m.id for m in invoice_moves]
        data['invoice_codes'] = [m.name for m in invoice_moves]
    except Exception:
        data['invoice_ids'] = []
        data['invoice_codes'] = []
    return data

def _invoice_status(inv):
    if inv.payment_state == 'paid':
        return 'paid'
    if inv.state == 'posted':
        return 'posted'
    return inv.state

def _invoice_payload(inv, with_lines=False, with_payments=False):
    amount_total = _money(inv.amount_total)
    amount_paid = amount_total - _money(inv.amount_residual)
    payload = {
        'id': inv.id,
        'code': inv.name,
        'status': _invoice_status(inv),
        'issue_date': inv.invoice_date,
        'due_date': inv.invoice_date_due,
        'currency': inv.currency_id.name if inv.currency_id \
                    else (inv.company_id.currency_id.name if inv.company_id else None),
        'amount_total': amount_total,
        'amount_paid': max(0.0, amount_paid),
        'amount_residual': _money(inv.amount_residual),
        'payment_state': inv.payment_state,  # paid / not_paid / partial
        'partner_id': inv.partner_id.id if inv.partner_id else None,
        'partner_name': inv.partner_id.display_name if inv.partner_id else None,
        'partner_phone': inv.partner_id.phone if inv.partner_id else None, 
        'magasin': {
            'id': inv.magasin_id.id if hasattr(inv, 'magasin_id') and inv.magasin_id else None,
            'name': inv.magasin_id.name if hasattr(inv, 'magasin_id') and inv.magasin_id else None,
            'code': inv.magasin_id.code if hasattr(inv, 'magasin_id') and inv.magasin_id else None,
        },
        'payment_link': getattr(inv, 'payment_link', False),
        'transaction_id': getattr(inv, 'transaction_id', False),
    }

    # Bloc locatif sur la facture (contrat + local)
    try:
        contract = getattr(inv, 'rental_contract_id', False)
        payload['rental'] = {
            "contract": _contract_payload(contract) if contract else None,
        }
    except Exception:
        payload['rental'] = None

    if with_lines:
        payload['items'] = [_invoice_line_payload(l) for l in inv.invoice_line_ids]
    if with_payments:
        pays = []
        try:
            receivables = inv.line_ids.filtered(lambda l: l.account_id.internal_type in ('receivable', 'payable'))
            for line in receivables:
                for m in (line.matched_debit_ids | line.matched_credit_ids):
                    pay_move = m.debit_move_id.move_id if m.debit_move_id else m.credit_move_id.move_id
                    pay = request.env['account.payment'].sudo().search([('move_id', '=', pay_move.id)], limit=1)
                    if pay:
                        pays.append(_payment_with_invoices_payload(pay))
        except Exception:
            pass
        payload['payments'] = pays

    return payload


# =========================
# Utilitaires de recherche
# =========================

def _find_invoice_by_tx(tx):
    """Recherche une facture par transaction_id ou payment_link."""
    domain = [
        ('move_type', 'in', ('out_invoice', 'out_refund')),
        '|', ('transaction_id', '=', tx),
             ('payment_link', '=', tx),
    ]
    return request.env['account.move'].sudo().search(domain, limit=1)


# ==============================
# Contrôleur fusionné (Unique)
# ==============================

class GestionPartner(http.Controller):

    # ---------- PARTNER: création / lecture / mise à jour ----------

    @http.route('/api/new_compte', methods=['POST'], type='http', auth='none', cors="*", csrf=False)
    def api_new_compte_post(self, **kw):
        data = _parse_body()
        if not data:
            return _json_message("Données invalides", 400)

        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        city = data.get('city')
        phone = data.get('phone')

        if not email or not name or not password:
            return _json_message("Champs requis: name, email, password", 400)

        _require_admin_env()

        country = request.env['res.country'].sudo().search([('id', '=', 204)], limit=1)
        if request.env['res.partner'].sudo().search([('email', '=', email)], limit=1):
            return _json_message("Un utilisateur avec cet email existe déjà", 400)

        company_choice = request.env['res.company'].sudo().search([('id', '=', 1)], limit=1)

        partner = request.env['res.partner'].sudo().create({
            'name': name,
            'email': email,
            'customer_rank': 1,
            'company_id': company_choice.id if company_choice else False,
            'city': city,
            'phone': phone,
            'is_company': False,
            'active': True,
            'type': 'contact',
            'company_name': company_choice.name if company_choice else False,
            'country_id': country.id or False,
            'password': password,
            'is_verified': False,
        })
        if partner:
            # envoi OTP initial
            try:
                partner.send_otp()
            except Exception:
                _logger.exception("Erreur lors de l'envoi OTP initial")
            return _json(_partner_payload(partner), 201)

        return _json_message("Compte client non créé, veuillez réessayer", 400)

    @http.route('/api/partnerByEmail/<email>', methods=['GET'], type='http', auth='none', cors="*")
    def api_partner_get_by_email(self, email):
        partner = request.env['res.partner'].sudo().search([('email', '=', email)], limit=1)
        if not partner:
            return _json_message("Compte client non trouvé", 404)
        return _json(_partner_payload(partner), 200)

    @http.route('/api/partner/compte/<int:id>/details', methods=['GET'], type='http', auth='none', cors="*")
    def api_partner_get_detail_by_id(self, id, **kw):
        _require_admin_env()
        partner = request.env['res.partner'].sudo().browse(id)
        if not partner.exists():
            return _json_message("Compte client non trouvé", 404)
        return _json(_partner_payload(partner), 200)

    @http.route('/api/partner/<int:partner_id>/update', methods=['PUT'], type='http', auth='public', cors="*", csrf=False)
    def api_partner_update(self, partner_id, **kw):
        _require_admin_env()
        data = _parse_body()
        if data is None:
            return _json_message("Données invalides", 400)

        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return _json_message("Compte client non trouvé", 404)

        update_fields = {
            'name': data.get('name'),
            'email': data.get('email'),
            'phone': data.get('partner_phone'),
            'city': data.get('partner_city'),
            # 'function': data.get('function'),
        }
        update_fields = {k: v for k, v in update_fields.items() if v is not None}
        partner.write(update_fields)
        return _json_message("Informations mises à jour avec succès", 200)

    @http.route('/api/partner/create-update/<email>', methods=['POST'], type='http', auth='none', cors="*", csrf=False)
    def api_partner_create_update(self, email, **kw):
        """Init/MAJ des infos + renvoi OTP."""
        _require_admin_env()
        data = _parse_body()
        if data is None:
            return _json_message("Données invalides", 400)

        partner = request.env['res.partner'].sudo().search([('email', '=', email)], limit=1)
        if not partner:
            return _json_message("Compte client non trouvé", 404)

        vals = {}
        if (v := data.get('name')) is not None: vals['name'] = v
        if (v := data.get('adresse')) is not None: vals['city'] = v
        if (v := data.get('telephone')) is not None: vals['phone'] = v
        if (v := data.get('password')) is not None: vals['password'] = v
        vals['is_verified'] = False

        partner.write(vals)
        try:
            partner.send_otp()
        except Exception:
            _logger.exception("Erreur lors du renvoi OTP /create-update")
        return _json_message("Compte mis à jour, OTP envoyé pour vérification", 200)

    @http.route('/api/partner/update-partner', methods=['GET'], type='http', auth='none', cors="*")
    def api_partner_bulk_update_children(self, **kw):
        _require_admin_env()
        partners = request.env['res.partner'].sudo().search([('parent_id', '!=', False)])
        for p in partners:
            # Exemple d’update massif ; adapte si besoin
            p.write({'is_verified': True})
            _logger.info("Partenaire mis à jour: %s", p.name)
        return _json_message("Partenaires mis à jour", 200)

    # ---------- OTP PARTNER ----------

    @http.route('/api/partner/<int:partner_id>/otp-code', methods=['GET'], type='http', auth='none', cors="*")
    def api_partner_otp(self, partner_id, **kw):
        _require_admin_env()
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return _json_message("Compte client non trouvé", 404)
        try:
            code = partner.send_otp()
            _logger.info("OTP %s for %s", code, partner.email or partner.phone)
        except Exception:
            _logger.exception("Erreur send_otp partner")
            return _json_message("Impossible d'envoyer le code OTP", 500)
        return _json_message("Code OTP envoyé avec succès", 200)

    @http.route('/api/partner/<email>/otp-resend', methods=['GET'], type='http', auth='none', cors="*")
    def api_partner_resend_otp(self, email, **kw):
        _require_admin_env()
        partner = request.env['res.partner'].sudo().search([('email', '=', email)], limit=1)
        if not partner:
            return _json_message("Compte client non trouvé", 404)
        try:
            partner.send_otp()
        except Exception:
            _logger.exception("Erreur resend_otp partner")
            return _json_message("Impossible d'envoyer le code OTP", 500)
        return _json_message("Code OTP renvoyé avec succès", 200)

    
    @http.route('/api/partner/otp-verification', methods=['POST'], type='http', auth='none', cors="*", csrf=False)
    def api_partner_otp_verify(self, **kw):
        _require_admin_env()
        data = _parse_body()
        if data is None:
            return _json_message("Données invalides", 400)

        # Normalisations
        raw_code = data.get('code')
        email = (data.get('email') or '').strip()

        if raw_code is None or not email:
            return _json_message("Champs requis: email, code", 400)

        # s'assure d'avoir '0007' et pas 7
        code = str(raw_code).strip()
        if not code.isdigit():
            return _json_message("Code OTP invalide ou expiré", 400)
        code = code.zfill(4)

        partner = request.env['res.partner'].sudo().search([('email', 'ilike', email)], limit=1)
        if not partner:
            return _json_message("Compte client non trouvé", 404)

        try:
            ok = partner.verify_otp(code)
        except Exception:
            _logger.exception("Erreur verify_otp partner")
            ok = False

        if not ok:
            return _json_message("Code OTP invalide ou expiré", 400)

        partner.sudo().write({'is_verified': True})
        return _json({"success": True, "partner": _partner_payload(partner)}, 200)

    # ---------- OTP via FACTURE ----------

    @http.route('/api/invoices/<string:tx>/send-otp', methods=['POST'], type='http', auth='none', cors="*", csrf=False)
    def api_invoice_send_otp(self, tx, **kw):
        """
        Envoie un OTP au partenaire lié à la facture identifiée par `tx`
        (transaction_id ou payment_link).
        Réponse: { success: bool, maskedPhone: str }
        """
        _require_admin_env()
        if not tx:
            return _json_message("Paramètre 'transaction' requis", 400)

        inv = _find_invoice_by_tx(tx)
        if not inv:
            return _json_message("Facture introuvable pour ce transaction id", 404)

        partner = inv.partner_id.sudo()
        if not partner:
            return _json_message("Partenaire introuvable", 404)

        phone = partner.mobile or partner.phone
        if not phone:
            return _json_message("Aucun numéro de téléphone associé au compte", 400)

        try:
            code = partner.send_otp()
            _logger.info("OTP (invoice) %s for partner %s (inv %s)", code, partner.id, inv.id)
        except Exception:
            _logger.exception("Erreur envoi OTP facture")
            return _json_message("Impossible d'envoyer le code OTP", 500)

        return _json({"success": True, "maskedPhone": _mask_phone(phone)}, 200)

    @http.route('/api/invoices/verify-otp', methods=['POST'], type='http', auth='none', cors="*", csrf=False)
    def api_invoice_verify_otp(self, **kw):
        """
        Vérifie un OTP pour la facture.
        Body: { "transaction": "...", "code": "1234" }
        Réponse: { success: bool, partner?: {...} }
        """
        _require_admin_env()
        data = _parse_body()
        if data is None:
            return _json_message("Données invalides", 400)

        tx = data.get('transaction')
        code = data.get('code')
        if not tx or not code:
            return _json_message("Champs requis: transaction, code", 400)

        inv = _find_invoice_by_tx(tx)
        if not inv:
            return _json_message("Facture introuvable pour ce transaction id", 404)

        partner = inv.partner_id.sudo()
        if not partner:
            return _json_message("Partenaire introuvable", 404)

        ok = False
        try:
            ok = partner.verify_otp(code)
        except Exception:
            _logger.exception("Erreur verify_otp (invoice)")
            ok = False

        if not ok:
            return _json({"success": False}, 400)

        # sécurité : marque vérifié si pas encore
        if not getattr(partner, 'is_verified', False):
            partner.write({'is_verified': True})

        return _json({"success": True, "partner": _partner_payload(partner)}, 200)

    # ---------- Billing utilitaires publics ----------

    @http.route('/api/account-move/by-transaction', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def invoice_by_transaction(self, **kw):
        args = _parse_args()
        tx = args.get('transaction')
        if not tx:
            return _json_message("Paramètre 'transaction' requis", 400)

        move = _find_invoice_by_tx(tx)
        if not move:
            return _json_message("Facture introuvable pour cette transaction", 404)
        # on renvoie lignes + paiements consolidés
        return _json({"invoice": _invoice_payload(move, with_lines=True, with_payments=True)}, 200)

    @http.route('/api/payments', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def payments_by_partner(self, **kw):
        """
        Historique de paiements consolidés depuis les reconciles des factures postées.
        GET ?partnerId=ID
        """
        _require_admin_env()
        args = _parse_args()
        partner_id = args.get('partnerId')
        if not partner_id:
            return _json_message("Paramètre 'partnerId' requis", 400)

        partner_id = int(partner_id)
        Move = request.env['account.move'].sudo()
        domain = [
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted'),
            ('partner_id', '=', partner_id),
        ]
        rows = []
        for m in Move.search(domain):
            code = m.name
            currency = m.currency_id.name or (m.company_id.currency_id.name if m.company_id else "XOF")
            try:
                for p in m._get_reconciled_info_JSON_values():
                    rows.append({
                        "id": p.get("payment_id") or p.get("move_id") or p.get("aml_id"),
                        "invoice_id": m.id,
                        "invoice_code": code,
                        "amount": _money(p.get("amount") or p.get("amount_currency")),
                        "currency": currency,
                        "method": p.get("journal_name") or p.get("account_name") or "PAYMENT",
                        "status": "SUCCEEDED",
                        "paid_at": p.get("date"),
                    })
            except Exception:
                paid = _money(m.amount_total - m.amount_residual)
                if paid > 0:
                    rows.append({
                        "id": f"agg-{m.id}",
                        "invoice_id": m.id,
                        "invoice_code": code,
                        "amount": paid,
                        "currency": currency,
                        "method": "PAYMENT",
                        "status": "SUCCEEDED" if m.payment_state in ('paid', 'in_payment', 'partial') else "PENDING",
                        "paid_at": str(m.invoice_date or m.date) if m.invoice_date else None,
                    })

        # tri du plus récent
        rows.sort(key=lambda r: (r.get("paid_at") or "", r["invoice_id"]), reverse=True)
        return _json({"payments": rows}, 200)
