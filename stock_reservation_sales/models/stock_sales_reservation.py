# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare

EXPIRY_DURATIONS = {
    "1h": relativedelta(hours=1),
    "4h": relativedelta(hours=4),
    "1d": relativedelta(days=1),
    "2d": relativedelta(days=2),
    "3d": relativedelta(days=3),
    "1w": relativedelta(weeks=1),
    "2w": relativedelta(weeks=2),
    "1m": relativedelta(months=1),
}


class StockSalesReservation(models.Model):
    _name = "stock.sales.reservation"
    _description = "Sales Stock Reservation"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(
        default="New",
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("reserved", "Reserved"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled"),
            ("done", "Delivered"),
        ],
        default="draft",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Salesperson",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        required=True,
        default=lambda self: self._default_warehouse(),
        domain="[('company_id', '=', company_id)]",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        domain="[('is_storable', '=', True)]",
        tracking=True,
    )
    uom_id = fields.Many2one(
        comodel_name="uom.uom",
        related="product_id.uom_id",
        string="Unit",
    )
    product_qty = fields.Float(
        string="Quantity",
        digits="Product Unit",
        default=1.0,
        required=True,
        tracking=True,
    )
    available_qty = fields.Float(
        string="Available",
        digits="Product Unit",
        compute="_compute_available_qty",
        help="Free quantity of the product in the selected warehouse.",
    )
    expiry_duration = fields.Selection(
        selection=[
            ("1h", "1 hour"),
            ("4h", "4 hours"),
            ("1d", "1 day"),
            ("2d", "2 days"),
            ("3d", "3 days"),
            ("1w", "1 week"),
            ("2w", "2 weeks"),
            ("1m", "1 month"),
        ],
        string="Expires in",
        default="1d",
        required=True,
        tracking=True,
    )
    date_reserved = fields.Datetime(readonly=True, copy=False)
    expiry_date = fields.Datetime(
        compute="_compute_expiry_date",
        store=True,
        copy=False,
        tracking=True,
        index=True,
    )
    note = fields.Text()
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Transfer",
        readonly=True,
        copy=False,
        index=True,
    )

    @api.model
    def _default_warehouse(self):
        return self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )

    @api.depends("date_reserved", "expiry_duration")
    def _compute_expiry_date(self):
        for record in self:
            if record.date_reserved and record.expiry_duration:
                record.expiry_date = (
                    record.date_reserved + EXPIRY_DURATIONS[record.expiry_duration]
                )
            else:
                record.expiry_date = False

    @api.depends("product_id", "warehouse_id")
    def _compute_available_qty(self):
        for record in self:
            if record.product_id and record.warehouse_id:
                product = record.product_id.sudo().with_context(
                    location=record.warehouse_id.lot_stock_id.id
                )
                record.available_qty = product.free_qty
            else:
                record.available_qty = 0.0

    @api.constrains("product_qty")
    def _check_product_qty(self):
        for record in self:
            if float_compare(record.product_qty, 0.0, precision_digits=6) <= 0:
                raise ValidationError(
                    self.env._("The quantity to reserve must be greater than zero.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("stock.sales.reservation")
                    or "New"
                )
        return super().create(vals_list)

    def unlink(self):
        if any(record.state == "reserved" for record in self):
            raise UserError(
                self.env._("You cannot delete an active reservation. Cancel it first.")
            )
        return super().unlink()

    def _prepare_picking_vals(self):
        self.ensure_one()
        location = self.warehouse_id.lot_stock_id
        picking_type = self.warehouse_id.int_type_id
        if not picking_type:
            raise UserError(
                self.env._(
                    "Warehouse %s has no internal transfer operation type.",
                    self.warehouse_id.display_name,
                )
            )
        return {
            "picking_type_id": picking_type.id,
            "location_id": location.id,
            "location_dest_id": location.id,
            "partner_id": self.partner_id.id,
            "origin": self.name,
            "company_id": self.company_id.id,
            "move_ids": [
                Command.create(
                    {
                        "product_id": self.product_id.id,
                        "product_uom_qty": self.product_qty,
                        "uom_id": self.product_id.uom_id.id,
                        "location_id": location.id,
                        "location_dest_id": location.id,
                        "company_id": self.company_id.id,
                    }
                )
            ],
        }

    def action_reserve(self):
        for record in self:
            if record.state != "draft":
                raise UserError(
                    self.env._("Only draft reservations can be reserved.")
                )
            # Salespeople do not have inventory rights: the stock operations
            # are done in sudo mode, the access is controlled on this model.
            picking = (
                self.env["stock.picking"]
                .sudo()
                .create(record._prepare_picking_vals())
            )
            picking.action_confirm()
            picking.action_assign()
            move = picking.move_ids
            if move.uom_id.compare(move.quantity, move.product_uom_qty) < 0:
                available = move.quantity
                # Raising discards the picking created above
                raise UserError(
                    self.env._(
                        "Not enough stock: only %(available)s %(uom)s of "
                        "%(product)s can be reserved.",
                        available=available,
                        uom=move.uom_id.display_name,
                        product=record.product_id.display_name,
                    )
                )
            record.write(
                {
                    "picking_id": picking.id,
                    "date_reserved": fields.Datetime.now(),
                    "state": "reserved",
                }
            )
        return True

    def _release_stock(self):
        """Cancel the linked transfer so the reserved quantities are freed."""
        for record in self.filtered("picking_id"):
            picking = record.picking_id.sudo()
            if picking.state not in ("done", "cancel"):
                picking.action_cancel()

    def action_cancel(self):
        for record in self:
            if record.state not in ("draft", "reserved"):
                raise UserError(
                    self.env._("Only draft or reserved reservations can be cancelled.")
                )
        self._release_stock()
        self.write({"state": "cancelled"})
        return True

    def action_set_draft(self):
        for record in self:
            if record.state not in ("expired", "cancelled"):
                raise UserError(
                    self.env._("Only expired or cancelled reservations can be reset.")
                )
        self.write({"state": "draft", "picking_id": False, "date_reserved": False})
        return True

    def _expire(self):
        self._release_stock()
        self.write({"state": "expired"})
        for record in self:
            record.message_post(
                body=self.env._(
                    "The reservation has expired and the stock was released."
                )
            )

    def _sync_with_picking(self):
        """Follow transfers processed by the warehouse team."""
        for record in self.filtered(lambda r: r.state == "reserved"):
            picking_state = record.picking_id.sudo().state
            if picking_state == "done":
                record.state = "done"
            elif picking_state == "cancel":
                record.state = "cancelled"

    @api.model
    def _cron_expire_reservations(self):
        reservations = self.search([("state", "=", "reserved")])
        reservations._sync_with_picking()
        expired = reservations.filtered(
            lambda r: r.state == "reserved" and r.expiry_date <= fields.Datetime.now()
        )
        expired._expire()
        return True
