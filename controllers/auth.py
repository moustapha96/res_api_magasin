
from .main import *  # error_response, successful_response, error_resp, error_response_401__invalid_token, token_store, generate_token, rest_cors_value, logging, json, werkzeug, request
import sys
import time
import re
from passlib.context import CryptContext
from odoo import http, fields
import logging

_logger = logging.getLogger(__name__)

# =========================
# Codes HTTP de succès
# =========================
OUT__auth_gettokens__SUCCESS_CODE = 200
OUT__auth_refreshtoken__SUCCESS_CODE = 200
OUT__auth_deletetokens__SUCCESS_CODE = 200


class ControllerREST(http.Controller):
    # ---------------------------------------------------------
    # Utilitaires tokens & paramètres
    # ---------------------------------------------------------
    def define_token_expires_in(self, token_type, jdata):
        token_lifetime = jdata.get(f'{token_type}_lifetime')
        try:
            token_lifetime = float(token_lifetime)
        except Exception:
            token_lifetime = None

        if isinstance(token_lifetime, (int, float)):
            expires_in = token_lifetime
        else:
            try:
                expires_in = float(
                    request.env['ir.config_parameter']
                    .sudo()
                    .get_param(f'rest_api.{token_type}_token_expires_in')
                )
            except Exception:
                expires_in = None

        return int(round(expires_in or (sys.maxsize - time.time())))

    # ---------------------------------------------------------
    # Helpers généraux
    # ---------------------------------------------------------
    def _no_cookie_response(self, status, payload):
        resp = werkzeug.wrappers.Response(
            status=status,
            content_type='application/json; charset=utf-8',
            headers=[('Cache-Control', 'no-store'), ('Pragma', 'no-cache')],
            response=json.dumps(payload),
        )
        # API stateless: ne pas poser de cookie session
        resp.set_cookie = lambda *a, **k: None
        return resp

    def _get_db_name(self):
        return request.session.db

    def _authenticate_admin(self):
        """Assure un env sudo non-public (ex. depuis auth='none')."""
        user = request.env['res.users'].sudo().browse(request.env.uid)
        if not user or user._is_public():
            admin_user = request.env.ref('base.user_admin')
            request.env = request.env(user=admin_user.id)

    def _authenticate_odoo_user(self):
        """
        Ouvre une session Odoo technique pour obtenir un uid valide côté /api.
        Tu peux paramétrer ces identifiants dans ir.config_parameter si besoin.
        """
        # DEV
        email_admin = 'ccbmtech@ccbm.sn'
        password_admin = 'password'

        # PROD (décommente si besoin)
        # email_admin = 'ccbmtech@ccbm.sn'
        # password_admin = 'ccbmtecH@987'

        try:
            request.session.authenticate(self._get_db_name(), email_admin, password_admin)
            return request.session.uid
        except Exception as e:
            _logger.error(f"Odoo authentication failed: {str(e)}")
            return None

    # ---------------------------------------------------------
    # Helpers validation/inputs
    # ---------------------------------------------------------
    def _get_request_data(self):
        """Fusion args + body JSON (tolérant)."""
        args = request.httprequest.args.to_dict(flat=True) or {}
        body = {}
        try:
            # get_json est plus tolérant qu'un json.loads sur data
            body = request.httprequest.get_json(silent=True) or {}
        except Exception:
            try:
                body = json.loads(request.httprequest.data or b'{}')
            except Exception:
                body = {}
        jdata = {}
        jdata.update(args)
        jdata.update(body)
        return jdata

    def _validate_credentials(self, jdata):
        username = (jdata.get('username') or '').strip()
        password = (jdata.get('password') or '')
        if not username or not password:
            raise ValueError("Empty value of 'username' or 'password'!")
        return username, password

    # ---------------------------------------------------------
    # Helpers Partner/Company/Parent
    # ---------------------------------------------------------
    def _normalize_phone(self, raw):
        """
        Normalise un téléphone pour la recherche:
        - enlève espaces, tirets, points, parenthèses
        - gère +221 / 00221 / 221
        - conserve uniquement les chiffres finaux utiles
        """
        if not raw:
            return None
        s = str(raw).strip()
        s = re.sub(r'[\s\-\.\(\)]', '', s)
        s = s.replace('+', '')
        # Supprime préfixes 00221 / 221
        if s.startswith('00221'):
            s = s[5:]
        elif s.startswith('221'):
            s = s[3:]
        # Supprimer zéros en tête superflus (ex: 0078...)
        s = re.sub(r'^0+', '', s)
        # Version longue avec 221 pour comparer aussi stockages complets
        with_cc = f'221{s}' if not s.startswith('221') else s
        return s, with_cc

    def _get_parent_data(self, user_partner):
        if user_partner.parent_id:
            return {
                'id': user_partner.parent_id.id,
                'name': user_partner.parent_id.name,
                'email': user_partner.parent_id.email,
                'phone': user_partner.parent_id.phone,
            }
        return {}

    def _get_company_data(self, user_partner):
        return {
            'id': user_partner.company_id.id if user_partner.company_id else None,
            'name': user_partner.company_id.name if user_partner.company_id else None,
            'email': user_partner.company_id.email if user_partner.company_id else None,
            'phone': user_partner.company_id.phone if user_partner.company_id else None,
        }

    # ---------------------------------------------------------
    # Password helpers
    # ---------------------------------------------------------
    def hash_password(self, password):
        pwd_context = CryptContext(schemes=["pbkdf2_sha512", "md5_crypt"], deprecated="md5_crypt")
        return pwd_context.hash(password)

    def check_password(self, password, hashed_password):
        pwd_context = CryptContext(schemes=["pbkdf2_sha512", "md5_crypt"], deprecated="md5_crypt")
        return pwd_context.verify(password, hashed_password)

    def is_hashed_password(self, password):
        if not password:
            return False
        pwd_context = CryptContext(schemes=["pbkdf2_sha512", "md5_crypt"], deprecated="md5_crypt")
        return bool(pwd_context.identify(password))

    # ---------------------------------------------------------
    # Lookup Partner & init password
    # ---------------------------------------------------------
    def _get_user_partner(self, username):
        """
        Recherche par email exact OU téléphone normalisé (champ phone OU mobile).
        IMPORTANT: domaine Odoo nécessite les opérateurs '|' pour OR.
        """
        self._authenticate_admin()

        # Cas email ?
        is_email = '@' in username
        if is_email:
            domain = [('email', '=', username)]
        else:
            short, with_cc = self._normalize_phone(username) or (None, None)
            # Si rien d'exploitable
            if not short and not with_cc:
                return request.env['res.partner'].sudo().browse([])
            # phone OU mobile (short) OU (221+short)
            domain = ['|', '|',
                      ('phone', 'ilike', short),
                      ('mobile', 'ilike', short),
                      ('phone', 'ilike', with_cc)]
            # on ajoute le mobile avec cc
            domain = ['|'] + domain + [('mobile', 'ilike', with_cc)]

        partner = request.env['res.partner'].sudo().search(domain, limit=1)
        _logger.info("Partner lookup with domain %s -> %s", domain, partner and partner.id)
        return partner

    def _verify_partner_password(self, user_partner, password):
        """
        - Si pas de mot de passe: initialiser (première connexion)
        - Si mdp en clair: valider et migrer vers hash
        - Si hashé: vérifier
        """
        if user_partner and not getattr(user_partner, 'password', None):
            hashed = self.hash_password(password)
            user_partner.sudo().write({'password': hashed, 'is_verified': True})
            _logger.info("Init password & verify for partner %s", user_partner.id)
            return True

        stored = user_partner.password
        if self.is_hashed_password(stored):
            return self.check_password(password, stored)

        # stocké en clair (ancien) ?
        if stored == password:
            hashed = self.hash_password(password)
            user_partner.sudo().write({'password': hashed})
            return True

        return False

    # ---------------------------------------------------------
    # Tokens + réponse success
    # ---------------------------------------------------------
    def _generate_and_save_tokens(self, uid):
        access_token = generate_token()
        refresh_token = generate_token()
        expires_in = 3600
        refresh_expires_in = max(7200, expires_in)

        token_store.save_all_tokens(
            request.env,
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            refresh_expires_in=refresh_expires_in,
            user_id=uid
        )
        return {
            'access_token': access_token,
            'expires_in': expires_in,
            'refresh_token': refresh_token,
            'refresh_expires_in': refresh_expires_in,
        }

    def _create_successful_response(self, uid, tokens, user_data, company_data, parent_data):
        payload = {
            'uid': uid,
            'user_context': request.session.context if uid else {},
            'company_id': request.env.user.company_id.id if uid else None,
            'user_info': user_data,
            'is_verified': user_data.get('is_verified', False),
            'company': company_data,
            'parent': parent_data,
            **tokens
        }
        return self._no_cookie_response(OUT__auth_gettokens__SUCCESS_CODE, payload)

    # ---------------------------------------------------------
    # ====== RENTAL HELPERS (résumés locatifs) ======
    # ---------------------------------------------------------
    def _serialize_property_short(self, p):
        return {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "building_id": p.building_id.id if p.building_id else None,
            "building_name": p.building_id.name if p.building_id else None,
            "monthly_rent": float(p.monthly_rent or 0.0),
        }

    def _serialize_invoice_short(self, inv):
        total = float(inv.amount_total or 0.0)
        residual = float(inv.amount_residual or 0.0)
        return {
            "id": inv.id,
            "code": inv.name,
            "status": inv.payment_state,  # paid / partial / not_paid / in_payment
            "amount_total": total,
            "amount_residual": residual,
            "partner_id": inv.partner_id.id if inv.partner_id else None,
            "due_date": str(inv.invoice_date_due) if inv.invoice_date_due else None,
            "currency": inv.currency_id.name if inv.currency_id else None,
        }

    def _get_partner_rental_summary(self, user_partner):
        RentalContract = request.env["rental.contract"].sudo()
        AccountMove = request.env["account.move"].sudo()
        Schedule = request.env["rental.payment.schedule"].sudo()

        contracts = RentalContract.search([("tenant_id", "=", user_partner.id)])
        active_contracts = contracts.filtered(lambda c: c.state == "active")

        invoices = AccountMove.search([
            ("rental_contract_id", "in", contracts.ids),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
        ])
        unpaid = invoices.filtered(lambda inv: inv.payment_state in ("not_paid", "partial"))
        unpaid_total = sum(unpaid.mapped("amount_residual"))

        current_properties = active_contracts.mapped("property_id")

        last_invoices = invoices.sorted(
            key=lambda m: (m.invoice_date or m.date or m.id), reverse=True
        )[:5]

        today = fields.Date.today()
        next_schedules = Schedule.search([
            ("contract_id", "in", active_contracts.ids),
        ]).filtered(
            lambda s: (not s.invoice_id) and (s.due_date and s.due_date >= today)
        ).sorted(key=lambda s: s.due_date)[:5]

        return {
            "active_contract_count": len(active_contracts),
            "total_contract_count": len(contracts),
            "unpaid_invoice_count": len(unpaid),
            "total_unpaid_rent": float(unpaid_total or 0.0),
            "current_properties": [self._serialize_property_short(p) for p in current_properties],
            "last_invoices": [self._serialize_invoice_short(inv) for inv in last_invoices],
            "next_due_schedules": [{
                "id": s.id,
                "contract_id": s.contract_id.id if s.contract_id else None,
                "due_date": str(s.due_date) if s.due_date else None,
                "amount": float(s.amount or 0.0),
                "state": s.state,
                "invoice_id": s.invoice_id.id if s.invoice_id else None,
            } for s in next_schedules],
        }

    # ---------------------------------------------------------
    # USER DATA (enrichi avec rental)
    # ---------------------------------------------------------
    def _get_user_data(self, user_partner, uid):
        data = {
            'id': user_partner.id,
            'uid': uid,
            'name': user_partner.name,
            'email': user_partner.email,
            'partner_id': user_partner.id,
            'partner_city': user_partner.city,
            'partner_phone': user_partner.phone,
            'country_id': user_partner.country_id.id,
            'country_name': user_partner.country_id.name,
            'country_code': user_partner.country_id.code,
            'country_phone_code': user_partner.country_id.phone_code,
            'is_verified': getattr(user_partner, 'is_verified', False),
            'avatar': getattr(user_partner, 'avatar', None),
            'parent_id': user_partner.parent_id.id if user_partner.parent_id else None,
            'function': user_partner.function or "",
            'is_tenant': bool(getattr(user_partner, 'is_tenant', False)),
            'whatsapp_number': getattr(user_partner, 'whatsapp_number', None),
            'preferred_payment_method': getattr(user_partner, 'preferred_payment_method', None),
        }

        try:
            if data['is_tenant']:
                data['rental'] = self._get_partner_rental_summary(user_partner)
        except Exception as e:
            _logger.exception("rental summary error: %s", e)
            data['rental'] = {}

        return data

    # ---------------------------------------------------------
    # AUTH: Refresh token
    # ---------------------------------------------------------
    @http.route('/api/auth/refresh_token', methods=['POST'], type='http', auth='none', cors=rest_cors_value, csrf=False)
    def api_auth_refreshtoken(self, **kw):
        jdata = self._get_request_data()

        refresh_token = jdata.get('refresh_token')
        if not refresh_token:
            return error_response(400, 'no_refresh_token', "No refresh token was provided in request!")

        refresh_token_data = token_store.fetch_by_refresh_token(request.env, refresh_token)
        if not refresh_token_data:
            return error_response_401__invalid_token()

        old_access_token = refresh_token_data['access_token']
        new_access_token = generate_token()
        expires_in = self.define_token_expires_in('access', jdata)
        uid = refresh_token_data['user_id']

        token_store.update_access_token(
            request.env,
            old_access_token=old_access_token,
            new_access_token=new_access_token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            user_id=uid
        )

        return self._no_cookie_response(
            OUT__auth_refreshtoken__SUCCESS_CODE,
            {'access_token': new_access_token, 'expires_in': expires_in}
        )

    # ---------------------------------------------------------
    # AUTH: Delete tokens
    # ---------------------------------------------------------
    @http.route('/api/auth/delete_tokens', methods=['POST'], type='http', auth='none', cors=rest_cors_value, csrf=False)
    def api_auth_deletetokens(self, **kw):
        jdata = self._get_request_data()
        refresh_token = jdata.get('refresh_token')
        if not refresh_token:
            return error_response(400, 'no_refresh_token', "No refresh token was provided in request!")

        token_store.delete_all_tokens_by_refresh_token(request.env, refresh_token)
        return successful_response(OUT__auth_deletetokens__SUCCESS_CODE, {})

    # ---------------------------------------------------------
    # AUTH: Login (GET tokens)
    # ---------------------------------------------------------
    @http.route('/api/auth/get_tokens', methods=['GET'], type='http', auth='public', cors='*', csrf=False)
    def api_auth_gettokens(self, **kw):
        try:
            jdata = self._get_request_data()
            username, password = self._validate_credentials(jdata)

            user_partner = self._get_user_partner(username)
            if not user_partner:
                return error_resp(400, "Email ou mot de passe incorrecte!")

            # si déjà un mdp existe mais non vérifié -> refuse
            if getattr(user_partner, 'password', None) and not getattr(user_partner, 'is_verified', False):
                return error_resp(400, "Email non verifié!")

            if not self._verify_partner_password(user_partner, password):
                return error_resp(401, "Email ou mot de passe incorrecte")

            uid = self._authenticate_odoo_user()
            if not uid:
                return error_response(401, 'odoo_user_authentication_failed', "Odoo User authentication failed!")

            tokens = self._generate_and_save_tokens(uid)
            user_data = self._get_user_data(user_partner, uid)
            company_data = self._get_company_data(user_partner)
            parent_data = self._get_parent_data(user_partner)

            return self._create_successful_response(uid, tokens, user_data, company_data, parent_data)

        except ValueError as ve:
            return error_response(400, 'bad_request', str(ve))
        except Exception as e:
            _logger.exception("Error in api_auth_gettokens: %s", e)
            return error_response(500, 'internal_server_error', str(e))

    # ---------------------------------------------------------
    # AUTH: Login (POST)
    # ---------------------------------------------------------
    @http.route('/api/auth/login', methods=['POST'], type='http', auth='none', cors=rest_cors_value, csrf=False)
    def api_auth_login_post(self, **kw):
        try:
            jdata = self._get_request_data()
            username, password = self._validate_credentials(jdata)

            user_partner = self._get_user_partner(username)
            if not user_partner:
                return error_resp(400, "Email ou mot de passe incorrecte!")

            if getattr(user_partner, 'password', None) and not getattr(user_partner, 'is_verified', False):
                return error_resp(400, "Email non verifié!")

            if not self._verify_partner_password(user_partner, password):
                return error_resp(401, "Email ou mot de passe incorrecte")

            uid = self._authenticate_odoo_user()
            if not uid:
                return error_response(401, 'odoo_user_authentication_failed', "Odoo User authentication failed!")

            tokens = self._generate_and_save_tokens(uid)
            user_data = self._get_user_data(user_partner, uid)
            company_data = self._get_company_data(user_partner)
            parent_data = self._get_parent_data(user_partner)

            return self._create_successful_response(uid, tokens, user_data, company_data, parent_data)

        except ValueError as ve:
            return error_response(400, 'bad_request', str(ve))
        except Exception as e:
            _logger.exception("Error in api_auth_login_post: %s", e)
            return error_response(500, 'internal_server_error', str(e))

    # ---------------------------------------------------------
    # /api/me (profil courant)
    # ---------------------------------------------------------
    @http.route('/api/me', methods=['GET'], type='http', auth='public', cors=rest_cors_value, csrf=False)
    def api_me(self, **kw):
        try:
            uid = request.session.uid or None
            if not uid:
                return error_response(401, 'unauthorized', 'Not logged')

            user_partner = request.env['res.partner'].sudo().browse(request.env.user.partner_id.id)
            user_data = self._get_user_data(user_partner, uid)
            company_data = self._get_company_data(user_partner)
            parent_data = self._get_parent_data(user_partner)

            return successful_response(200, {
                'uid': uid,
                'user_info': user_data,
                'company': company_data,
                'parent': parent_data
            })
        except Exception as e:
            _logger.exception("/api/me error: %s", e)
            return error_response(500, 'internal_server_error', str(e))
