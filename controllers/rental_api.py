# controllers/rental_api.py
# -*- coding: utf-8 -*-
from odoo import http, fields, _
from odoo.http import request
import json
import werkzeug
import logging
from dateutil.relativedelta import relativedelta
import requests  # optional, used for external payment providers (Wave/OM) if configurés

_logger = logging.getLogger(__name__)

# -------------------------
# Helpers JSON / util
# -------------------------
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
    return request.httprequest.args.to_dict()

def _require_admin_env():
    """For public endpoints — exécuter en sudo admin (pattern existant dans ton projet)."""
    try:
        if not request.env.user or request.env.user._is_public():
            admin_user = request.env.ref('base.user_admin')
            request.env = request.env(user=admin_user.id)
    except Exception:
        # fallback: keep env
        pass

def _money(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0

# -------------------------
# Serializers
# -------------------------
def _building_payload(b):
    return {
        "id": b.id,
        "name": b.name,
        "code": b.code,
        "street": b.street,
        "street2": b.street2,
        "city": b.city,
        "state_id": b.state_id.id if b.state_id else None,
        "state_name": b.state_id.name if b.state_id else None,
        "zip": b.zip,
        "country_id": b.country_id.id if b.country_id else None,
        "country_name": b.country_id.name if b.country_id else None,
        "construction_year": b.construction_year,
        "total_floors": b.total_floors,
        "total_surface": b.total_surface,
        "property_count": b.property_count,
        "available_property_count": b.available_property_count,
        "rented_property_count": b.rented_property_count,
        "occupancy_rate": b.occupancy_rate,
        "total_monthly_rent": _money(b.total_monthly_rent),
        "total_unpaid": _money(b.total_unpaid),
        "manager_id": b.manager_id.id if b.manager_id else None,
        "owner_id": b.owner_id.id if b.owner_id else None,
        "company_id": b.company_id.id if b.company_id else None,
        "description": b.description,
        "note": b.note,
        "active": b.active,
    }

def _property_payload(p, with_contract=False):
    pl = {
        "id": p.id,
        "name": p.name,
        "building_id": p.building_id.id if p.building_id else None,
        "building_name": p.building_id.name if p.building_id else None,
        "property_type": p.property_type,
        "surface_area": p.surface_area,
        "floor": p.floor,
        "status": p.status,
        "monthly_rent": _money(p.monthly_rent),
        "currency": p.currency_id.name if p.currency_id else None,
        "description": p.description,
        "address": p.address,
        "note": p.note,
        "active": p.active,
        "current_tenant_id": p.current_tenant_id.id if p.current_tenant_id else None,
        "current_contract_id": p.current_contract_id.id if p.current_contract_id else None,
        "contract_count": p.contract_count,
        "total_unpaid_invoices": _money(p.total_unpaid_invoices),
    }
    if with_contract and p.current_contract_id:
        pl["current_contract"] = _contract_payload(p.current_contract_id, with_schedule=True, with_invoices=True)
    return pl

def _schedule_payload(s):
    return {
        "id": s.id,
        "contract_id": s.contract_id.id if s.contract_id else None,
        "due_date": str(s.due_date) if s.due_date else None,
        "amount": _money(s.amount),
        "state": s.state,
        "invoice_id": s.invoice_id.id if getattr(s, 'invoice_id', False) else None,
    }

def _invoice_payload(inv):
    total = _money(inv.amount_total)
    residual = _money(inv.amount_residual)
    paid = max(0.0, total - residual)
    return {
        "id": inv.id,
        "code": inv.name,
        "move_type": inv.move_type,
        "status": inv.payment_state,
        "issue_date": str(inv.invoice_date) if inv.invoice_date else None,
        "due_date": str(inv.invoice_date_due) if inv.invoice_date_due else None,
        "currency": inv.currency_id.name if inv.currency_id else None,
        "amount_total": total,
        "amount_paid": paid,
        "amount_residual": residual,
        "partner_id": inv.partner_id.id if inv.partner_id else None,
        "partner_name": inv.partner_id.display_name if inv.partner_id else None,
        "invoice_lines": [{
            "name": l.name,
            "quantity": l.quantity,
            "price_unit": _money(l.price_unit),
            "subtotal": _money(getattr(l, 'price_subtotal', 0.0))
        } for l in getattr(inv, 'invoice_line_ids', [])],
    }

def _contract_payload(c, with_schedule=True, with_invoices=False):
    payload = {
        "id": c.id,
        "name": c.name,
        "state": c.state,
        "property_id": c.property_id.id if c.property_id else None,
        "property_name": c.property_id.name if c.property_id else None,
        "tenant_id": c.tenant_id.id if c.tenant_id else None,
        "tenant_name": c.tenant_id.display_name if c.tenant_id else None,
        "start_date": str(c.start_date) if c.start_date else None,
        "end_date": str(c.end_date) if c.end_date else None,
        "duration_months": c.duration_months,
        "monthly_rent": _money(c.monthly_rent),
        "payment_day": c.payment_day,
        "payment_frequency": c.payment_frequency,
        "deposit_amount": _money(c.deposit_amount),
        "deposit_paid": bool(c.deposit_paid),
        "auto_generate_invoices": bool(c.auto_generate_invoices),
        "auto_send_invoices": bool(c.auto_send_invoices),
        "send_sms": bool(c.send_sms),
        "send_whatsapp": bool(c.send_whatsapp),
        "invoice_count": c.invoice_count,
        "paid_invoice_count": c.paid_invoice_count,
        "unpaid_invoice_count": c.unpaid_invoice_count,
        "total_unpaid": _money(c.total_unpaid),
    }
    if with_schedule:
        payload["payment_schedule"] = [_schedule_payload(s) for s in c.payment_schedule_ids]
    if with_invoices:
        payload["invoices"] = [_invoice_payload(inv) for inv in c.invoice_ids]
    return payload

# -------------------------
# Controller principal
# -------------------------
class RentalApi(http.Controller):

    # -------------
    # Buildings
    # -------------
    @http.route('/api/rent/buildings', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def list_buildings(self, **kw):
        _require_admin_env()
        args = _parse_args()
        q = (args.get('q') or '').strip()
        domain = []
        if q:
            domain += ['|', ('name', 'ilike', q), ('code', 'ilike', q)]
        buildings = request.env['rental.building'].sudo().search(domain, order='name asc')
        return _json([_building_payload(b) for b in buildings], 200)

    @http.route('/api/rent/buildings/<int:building_id>', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def get_building(self, building_id, **kw):
        _require_admin_env()
        b = request.env['rental.building'].sudo().browse(building_id)
        if not b.exists():
            return _json_message("Immeuble introuvable", 404)
        return _json(_building_payload(b), 200)

    # -------------
    # Properties
    # -------------
    @http.route('/api/rent/properties', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def list_properties(self, **kw):
        _require_admin_env()
        args = _parse_args()
        q = (args.get('q') or '').strip()
        status = (args.get('status') or '').strip()
        building_id = int(args.get('building_id')) if args.get('building_id') else None

        domain = []
        if q:
            domain += ['|', ('name', 'ilike', q), ('description', 'ilike', q)]
        if status:
            domain += [('status', '=', status)]
        if building_id:
            domain += [('building_id', '=', building_id)]

        props = request.env['rental.property'].sudo().search(domain, order='name asc')
        return _json([_property_payload(p, with_contract=True) for p in props], 200)

    @http.route('/api/rent/properties/<int:prop_id>', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def get_property(self, prop_id, **kw):
        _require_admin_env()
        p = request.env['rental.property'].sudo().browse(prop_id)
        if not p.exists():
            return _json_message("Local introuvable", 404)
        return _json(_property_payload(p, with_contract=True), 200)

    # -------------
    # Contracts
    # -------------
    @http.route('/api/rent/contracts', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def list_contracts(self, **kw):
        _require_admin_env()
        args = _parse_args()
        tenant_id = int(args.get('tenant_id')) if args.get('tenant_id') else None
        property_id = int(args.get('property_id')) if args.get('property_id') else None
        state = (args.get('state') or '').strip()

        domain = []
        if tenant_id:
            domain += [('tenant_id', '=', tenant_id)]
        if property_id:
            domain += [('property_id', '=', property_id)]
        if state:
            domain += [('state', '=', state)]

        contracts = request.env['rental.contract'].sudo().search(domain, order='start_date desc, id desc')
        return _json([_contract_payload(c, with_schedule=False, with_invoices=False) for c in contracts], 200)

    @http.route('/api/rent/contracts/<int:contract_id>', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def get_contract(self, contract_id, **kw):
        _require_admin_env()
        c = request.env['rental.contract'].sudo().browse(contract_id)
        if not c.exists():
            return _json_message("Contrat introuvable", 404)
        return _json(_contract_payload(c, with_schedule=True, with_invoices=True), 200)

    # -------------
    # Contract actions: confirm/terminate/expire/regenerate/generate invoice
    # -------------
    @http.route('/api/rent/contracts/<int:contract_id>/confirm', type='http', auth='none', methods=['POST'], cors="*", csrf=False)
    def confirm_contract(self, contract_id, **kw):
        _require_admin_env()
        c = request.env['rental.contract'].sudo().browse(contract_id)
        if not c.exists():
            return _json_message("Contrat introuvable", 404)
        try:
            c.action_confirm()
        except Exception as e:
            _logger.exception("Erreur action_confirm: %s", e)
            return _json({"error": str(e)}, 400)
        return _json(_contract_payload(c, with_schedule=True, with_invoices=True), 200)

    @http.route('/api/rent/contracts/<int:contract_id>/terminate', type='http', auth='none', methods=['POST'], cors="*", csrf=False)
    def terminate_contract(self, contract_id, **kw):
        _require_admin_env()
        c = request.env['rental.contract'].sudo().browse(contract_id)
        if not c.exists():
            return _json_message("Contrat introuvable", 404)
        c.action_terminate()
        return _json(_contract_payload(c, with_schedule=True, with_invoices=True), 200)

    @http.route('/api/rent/contracts/<int:contract_id>/expire', type='http', auth='none', methods=['POST'], cors="*", csrf=False)
    def expire_contract(self, contract_id, **kw):
        _require_admin_env()
        c = request.env['rental.contract'].sudo().browse(contract_id)
        if not c.exists():
            return _json_message("Contrat introuvable", 404)
        c.action_expire()
        return _json(_contract_payload(c, with_schedule=True, with_invoices=True), 200)

    @http.route('/api/rent/contracts/<int:contract_id>/regenerate-schedule', type='http', auth='none', methods=['POST'], cors="*", csrf=False)
    def regenerate_schedule(self, contract_id, **kw):
        _require_admin_env()
        c = request.env['rental.contract'].sudo().browse(contract_id)
        if not c.exists():
            return _json_message("Contrat introuvable", 404)
        c._generate_payment_schedule()
        return _json({"payment_schedule": [_schedule_payload(s) for s in c.payment_schedule_ids]}, 200)

    @http.route('/api/rent/contracts/<int:contract_id>/generate-next-invoice', type='http', auth='none', methods=['POST'], cors="*", csrf=False)
    def generate_next_invoice(self, contract_id, **kw):
        _require_admin_env()
        c = request.env['rental.contract'].sudo().browse(contract_id)
        if not c.exists():
            return _json_message("Contrat introuvable", 404)
        inv = c._generate_next_invoice()
        if not inv:
            return _json_message("Aucune échéance à facturer pour l’instant", 200)
        return _json({"invoice": _invoice_payload(inv)}, 201)

    # -------------
    # Invoices
    # -------------
    @http.route('/api/rent/contracts/<int:contract_id>/invoices', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def list_contract_invoices(self, contract_id, **kw):
        _require_admin_env()
        c = request.env['rental.contract'].sudo().browse(contract_id)
        if not c.exists():
            return _json_message("Contrat introuvable", 404)
        moves = c.invoice_ids.sorted(key=lambda m: (m.invoice_date or m.date or m.id), reverse=True)
        return _json([_invoice_payload(m) for m in moves], 200)

    @http.route('/api/rent/invoices/<int:move_id>', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def get_invoice(self, move_id, **kw):
        _require_admin_env()
        inv = request.env['account.move'].sudo().browse(move_id)
        if not inv.exists() or inv.move_type not in ('out_invoice', 'out_refund'):
            return _json_message("Facture introuvable", 404)
        return _json({"invoice": _invoice_payload(inv)}, 200)

    # Send invoice notification (email + sms + whatsapp)
    @http.route('/api/rent/invoices/<int:move_id>/send', type='http', auth='none', methods=['POST'], cors="*", csrf=False)
    def send_invoice(self, move_id, **kw):
        _require_admin_env()
        data = _parse_body() or {}
        channel = data.get('channel')  # 'email'|'sms'|'whatsapp'|'all'
        inv = request.env['account.move'].sudo().browse(move_id)
        if not inv.exists():
            return _json_message("Facture introuvable", 404)

        # Email via template if exists
        template = request.env.ref('rental.email_template_rental_invoice', raise_if_not_found=False)
        results = {"email": False, "sms": False, "whatsapp": False}
        try:
            if channel in (None, 'email', 'all') and template:
                template.send_mail(inv.id, force_send=True)
                results['email'] = True
        except Exception as e:
            _logger.exception("Erreur envoi email facture: %s", e)

        # SMS
        try:
            if channel in ('sms', 'all') and inv.partner_id and inv.partner_id.mobile:
                # ton helper SMS existant : _message_sms ou fournisseur
                msg = _('Bonjour %s, votre facture %s de %s est disponible. Merci.') % (
                    inv.partner_id.name, inv.name, inv.amount_total)
                inv.partner_id._message_sms(body=msg, partner_ids=inv.partner_id.ids)
                results['sms'] = True
        except Exception as e:
            _logger.exception("Erreur SMS facture: %s", e)

        # WhatsApp (si configuré)
        try:
            if channel in ('whatsapp', 'all') and inv.partner_id and (inv.partner_id.whatsapp_number or inv.partner_id.mobile):
                # exemple simple : tu dois avoir ton propre provider implémenté
                # ici on simule l'appel et renvoie True si provider ok
                # TODO: replace by ton provider
                results['whatsapp'] = False
        except Exception as e:
            _logger.exception("Erreur WhatsApp facture: %s", e)

        return _json({"sent": results}, 200)

    # Mark invoice as paid (simple reconciliation helper for API)
    @http.route('/api/rent/invoices/<int:move_id>/mark-paid', type='http', auth='none', methods=['POST'], cors="*", csrf=False)
    def mark_invoice_paid(self, move_id, **kw):
        """
        Body:
          {
            "amount": float,  # optional (default = amount_total)
            "journal_id": int,  # optional
            "payment_date": "YYYY-MM-DD" optional
          }
        NOTE: c'est une solution simple pour l'API. En production, utiliser le workflow comptable + paiements enregistrés.
        """
        _require_admin_env()
        jdata = _parse_body() or {}
        amount = float(jdata.get('amount') or 0.0)
        payment_date = jdata.get('payment_date') or fields.Date.today()
        journal_id = jdata.get('journal_id')

        inv = request.env['account.move'].sudo().browse(move_id)
        if not inv.exists():
            return _json_message("Facture introuvable", 404)

        try:
            # Default amount = invoice.amount_residual
            if not amount or amount <= 0:
                amount = float(inv.amount_residual or inv.amount_total or 0.0)

            # Créer un paiement simple (account.payment) et valider
            Payment = request.env['account.payment'].sudo()
            payment_vals = {
                'payment_type': 'inbound',
                'partner_id': inv.partner_id.id,
                'amount': amount,
                'currency_id': inv.currency_id.id if inv.currency_id else inv.company_id.currency_id.id,
                'payment_date': payment_date,
                'communication': inv.name,
            }
            if journal_id:
                payment_vals['journal_id'] = journal_id

            payment = Payment.create(payment_vals)
            # post payment and reconcile with invoice
            payment.action_post()
            # reconcile with invoice's receivable move lines
            lines = (payment.move_id + inv.line_ids).filtered(lambda r: r.account_id.internal_type in ('receivable', 'payable'))
            # use Odoo reconcile tools: try full reconcile
            try:
                # try partial/full reconcile via write on matched_ids is complex; use invoice._recompute_payment_state
                inv._compute_invoice_payment_status()
            except Exception:
                pass

            return _json({"ok": True, "payment_id": payment.id}, 200)
        except Exception as e:
            _logger.exception("Erreur marquer facture payée: %s", e)
            return _json({"ok": False, "error": str(e)}, 500)

    # -------------
    # Partner-specific: exposer tout ce dont le partner a besoin
    # -------------
    @http.route('/api/rent/partner/<int:partner_id>/dashboard', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def partner_dashboard(self, partner_id, **kw):
        """
        Retourne:
           - contrats (actifs/historique)
           - factures (postées)
           - prochaines échéances (schedules)
           - locaux actuels
           - totaux impayés
        """
        _require_admin_env()
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return _json_message("Partner introuvable", 404)

        RentalContract = request.env['rental.contract'].sudo()
        AccountMove = request.env['account.move'].sudo()
        Schedule = request.env['rental.payment.schedule'].sudo()

        contracts = RentalContract.search([('tenant_id', '=', partner.id)])
        active_contracts = contracts.filtered(lambda c: c.state == 'active')
        properties = active_contracts.mapped('property_id')

        invoices = AccountMove.search([
            ('rental_contract_id', 'in', contracts.ids),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted')
        ]).sorted(key=lambda m: (m.invoice_date or m.date or m.id), reverse=True)

        unpaid = invoices.filtered(lambda inv: inv.payment_state in ('not_paid', 'partial'))
        unpaid_total = sum(unpaid.mapped('amount_residual'))

        today = fields.Date.today()
        next_schedules = Schedule.search([('contract_id', 'in', active_contracts.ids)]).filtered(
            lambda s: (not s.invoice_id) and (s.due_date and s.due_date >= today)
        ).sorted(key=lambda s: s.due_date)[:10]

        result = {
            "partner_id": partner.id,
            "partner_name": partner.name,
            "active_contracts": [_contract_payload(c, with_schedule=True, with_invoices=False) for c in active_contracts],
            "all_contracts": [_contract_payload(c, with_schedule=False, with_invoices=False) for c in contracts],
            "properties": [_property_payload(p, with_contract=True) for p in properties],
            "last_invoices": [_invoice_payload(inv) for inv in invoices[:10]],
            "unpaid_count": len(unpaid),
            "unpaid_total": _money(unpaid_total),
            "next_due_schedules": [_schedule_payload(s) for s in next_schedules],
        }
        return _json(result, 200)

    @http.route('/api/rent/partner/<int:partner_id>/invoices', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def partner_invoices(self, partner_id, **kw):
        _require_admin_env()
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return _json_message("Partner introuvable", 404)
        # récupérer toutes les invoices liées aux contrats du partner
        contracts = request.env['rental.contract'].sudo().search([('tenant_id', '=', partner.id)])
        invoices = request.env['account.move'].sudo().search([
            ('rental_contract_id', 'in', contracts.ids),
            ('move_type', '=', 'out_invoice')
        ], order='invoice_date desc, id desc')
        return _json([_invoice_payload(inv) for inv in invoices], 200)

    @http.route('/api/rent/partner/<int:partner_id>/contracts', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def partner_contracts(self, partner_id, **kw):
        _require_admin_env()
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return _json_message("Partner introuvable", 404)
        contracts = request.env['rental.contract'].sudo().search([('tenant_id', '=', partner.id)], order='start_date desc')
        return _json([_contract_payload(c, with_schedule=True, with_invoices=True) for c in contracts], 200)

    @http.route('/api/rent/partner/<int:partner_id>/properties', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def partner_properties(self, partner_id, **kw):
        _require_admin_env()
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return _json_message("Partner introuvable", 404)
        contracts = request.env['rental.contract'].sudo().search([('tenant_id', '=', partner.id), ('state', '=', 'active')])
        props = contracts.mapped('property_id')
        return _json([_property_payload(p, with_contract=True) for p in props], 200)

    @http.route('/api/rent/schedules/<int:schedule_id>', type='http', auth='none', methods=['GET'], cors="*", csrf=False)
    def get_schedule(self, schedule_id, **kw):
        _require_admin_env()
        s = request.env['rental.payment.schedule'].sudo().browse(schedule_id)
        if not s.exists():
            return _json_message("Échéance introuvable", 404)



    def _status_from_payment_state(self, move):
        """
        Mappe le payment_state Odoo vers les statuts attendus côté front :
          paid | not_paid | partial | overdue | posted | draft
        """
        ps = (move.payment_state or "").lower()
        if ps in ("paid",):
            return "paid"
        if ps in ("not_paid", "invoicing_legacy"):
            return "not_paid"
        if ps in ("partial", "in_payment"):
            return "partial"
        # "overdue" : si non payé et échéance dépassée
        try:
            if move.invoice_date_due and move.payment_state not in ("paid",) and move.invoice_date_due < fields.Date.context_today(move):
                return "overdue"
        except Exception:
            pass
        # fallback sur l'état comptable
        if move.state == "posted":
            return "posted"
        if move.state == "draft":
            return "draft"
        return ps or move.state or "draft"

    def _serialize_invoice(self, move):
        """
        Normalise la facture pour le front:
        {
          id, code, move_type, status, issue_date, due_date, currency,
          amount_total, amount_paid, amount_residual, partner_id, partner_name,
          invoice_lines: [{name, quantity, price_unit, subtotal}],
          items: [{id, description, quantity, unit_price, total}]
        }
        """
        amount_total = float(move.amount_total or 0.0)
        amount_residual = float(move.amount_residual or 0.0)
        amount_paid = max(0.0, amount_total - amount_residual)

        # lignes au format API (invoice_lines) + "items" pour ta vue mobile
        inv_lines = []
        items = []
        for idx, line in enumerate(move.invoice_line_ids):
            row = {
                "name": line.name or "",
                "quantity": float(line.quantity or 0.0),
                "price_unit": float(line.price_unit or 0.0),
                "subtotal": float(line.price_subtotal or 0.0),
            }
            inv_lines.append(row)
            items.append({
                "id": line.id or idx,
                "description": line.name or "",
                "quantity": float(line.quantity or 0.0),
                "unit_price": float(line.price_unit or 0.0),
                "total": float(line.price_subtotal or 0.0),
            })

        data = {
            "id": move.id,
            "code": move.name,
            "move_type": move.move_type,
            "status": self._status_from_payment_state(move),
            "issue_date": move.invoice_date.isoformat() if move.invoice_date else None,
            "due_date": move.invoice_date_due.isoformat() if move.invoice_date_due else None,
            "currency": move.currency_id.name,
            "amount_total": amount_total,
            "amount_paid": amount_paid,
            "amount_residual": amount_residual,
            "partner_id": move.partner_id.id if move.partner_id else None,
            "partner_name": move.partner_id.display_name if move.partner_id else None,
            "invoice_lines": inv_lines,
            # en plus (utile pour FactureMagasin.jsx)
            "items": items,
        }
        # si tu veux exposer le lien de paiement/transaction (optionnel)
        if hasattr(move, "transaction_id"):
            data["transaction_id"] = move.transaction_id
        if hasattr(move, "payment_link"):
            data["payment_link"] = move.payment_link
        return data

    def _json(self, payload, status=200):
        return request.make_response(
            headers=[("Content-Type", "application/json; charset=utf-8")],
            data=json.dumps(payload),
            status=status,
        )

    # --- Endpoint public ---

    @http.route("/api/account-move/by-transaction", type="http", auth="public", methods=["GET"], csrf=False, cors="*")
    def api_invoice_by_transaction(self, **kw):
        """
        GET /api/account-move/by-transaction?transaction=<uuid>
        Réponse: { "invoice": { ...normalisé... } }
        """
        tx = (kw.get("transaction") or "").strip()
        if not tx:
            return self._json({"error": "missing_transaction", "message": "Paramètre 'transaction' requis."}, status=400)

        # recherche facture par transaction_id
        Move = request.env["account.move"].sudo()
        move = Move.search([("transaction_id", "=", tx), ("move_type", "in", ("out_invoice", "out_refund"))], limit=1)
        if not move:
            return self._json({"error": "not_found", "message": "Aucune facture pour cette transaction."}, status=404)

        # sérialisation
        data = self._serialize_invoice(move)
        return self._json({"invoice": data}, status=200)



   