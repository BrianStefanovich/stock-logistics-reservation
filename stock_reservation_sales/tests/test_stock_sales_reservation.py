# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form
from odoo.tests.common import TransactionCase


class TestStockSalesReservation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Reservation product", "type": "consu", "is_storable": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 10.0
        )
        group = cls.env.ref("stock_reservation_sales.group_sales_reservation_user")
        cls.seller = cls.env["res.users"].create(
            {
                "name": "Seller",
                "login": "seller_reservation",
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.seller2 = cls.env["res.users"].create(
            {
                "name": "Seller 2",
                "login": "seller2_reservation",
                "group_ids": [(6, 0, [group.id])],
            }
        )

    def _create_reservation(self, qty=4.0, user=None, **kwargs):
        env = self.env if user is None else self.env(user=user)
        vals = {
            "product_id": self.product.id,
            "product_qty": qty,
            "warehouse_id": self.warehouse.id,
        }
        vals.update(kwargs)
        return env["stock.sales.reservation"].create(vals)

    def _free_qty(self):
        return self.product.with_context(
            location=self.warehouse.lot_stock_id.id
        ).free_qty

    def test_default_expiry(self):
        reservation = self._create_reservation()
        self.assertEqual(reservation.expiry_duration, "1d")
        self.assertFalse(reservation.expiry_date)

    def test_reserve_and_expiry_date(self):
        reservation = self._create_reservation(qty=4.0, expiry_duration="4h")
        reservation.action_reserve()
        self.assertEqual(reservation.state, "reserved")
        self.assertEqual(reservation.picking_id.state, "assigned")
        self.assertEqual(self._free_qty(), 6.0)
        self.assertEqual(
            reservation.expiry_date,
            reservation.date_reserved + relativedelta(hours=4),
        )
        reservation.expiry_duration = "1w"
        self.assertEqual(
            reservation.expiry_date,
            reservation.date_reserved + relativedelta(weeks=1),
        )

    def test_not_enough_stock(self):
        reservation = self._create_reservation(qty=11.0)
        with self.assertRaises(UserError):
            reservation.action_reserve()
        self.assertEqual(reservation.state, "draft")
        self.assertEqual(self._free_qty(), 10.0)

    def test_cancel_releases_stock(self):
        reservation = self._create_reservation()
        reservation.action_reserve()
        reservation.action_cancel()
        self.assertEqual(reservation.state, "cancelled")
        self.assertEqual(reservation.picking_id.state, "cancel")
        self.assertEqual(self._free_qty(), 10.0)

    def test_cron_expires_only_overdue(self):
        overdue = self._create_reservation(qty=3.0, expiry_duration="1h")
        active = self._create_reservation(qty=2.0, expiry_duration="1d")
        (overdue | active).action_reserve()
        self.assertEqual(self._free_qty(), 5.0)
        overdue.date_reserved = fields.Datetime.now() - relativedelta(hours=2)
        self.env["stock.sales.reservation"]._cron_expire_reservations()
        self.assertEqual(overdue.state, "expired")
        self.assertEqual(overdue.picking_id.state, "cancel")
        self.assertEqual(active.state, "reserved")
        self.assertEqual(self._free_qty(), 8.0)

    def test_reset_to_draft_and_reserve_again(self):
        reservation = self._create_reservation()
        reservation.action_reserve()
        reservation.date_reserved = fields.Datetime.now() - relativedelta(days=2)
        self.env["stock.sales.reservation"]._cron_expire_reservations()
        reservation.action_set_draft()
        reservation.action_reserve()
        self.assertEqual(reservation.state, "reserved")
        self.assertEqual(self._free_qty(), 6.0)

    def test_cron_follows_done_picking(self):
        reservation = self._create_reservation()
        reservation.action_reserve()
        reservation.picking_id.button_validate()
        self.env["stock.sales.reservation"]._cron_expire_reservations()
        self.assertEqual(reservation.state, "done")

    def test_cannot_unlink_reserved(self):
        reservation = self._create_reservation()
        reservation.action_reserve()
        with self.assertRaises(UserError):
            reservation.unlink()

    def test_seller_without_inventory_rights(self):
        reservation = self._create_reservation(user=self.seller)
        reservation.action_reserve()
        self.assertEqual(reservation.state, "reserved")
        self.assertEqual(reservation.user_id, self.seller)
        self.assertEqual(reservation.with_user(self.seller).available_qty, 6.0)
        with self.assertRaises(AccessError):
            self.env["stock.picking"].with_user(self.seller).search([])

    def test_seller_only_sees_own_reservations(self):
        mine = self._create_reservation(qty=1.0, user=self.seller)
        theirs = self._create_reservation(qty=1.0, user=self.seller2)
        visible = self.env["stock.sales.reservation"].with_user(self.seller).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)

    def test_manager_sees_all_and_reassigns(self):
        manager_group = self.env.ref(
            "stock_reservation_sales.group_sales_reservation_manager"
        )
        manager = self.env["res.users"].create(
            {
                "name": "Reservation manager",
                "login": "manager_reservation",
                "group_ids": [(6, 0, [manager_group.id])],
            }
        )
        r1 = self._create_reservation(qty=1.0, user=self.seller)
        r2 = self._create_reservation(qty=2.0, user=self.seller2)
        (r1 | r2).sudo().action_reserve()
        as_manager = self.env["stock.sales.reservation"].with_user(manager)
        reserved = as_manager.search([("state", "=", "reserved")])
        self.assertEqual(reserved & (r1 | r2), r1 | r2)
        grouped = as_manager._read_group(
            [("state", "=", "reserved")], ["user_id"], ["product_qty:sum"]
        )
        self.assertEqual(
            {user.id: qty for user, qty in grouped},
            {self.seller.id: 1.0, self.seller2.id: 2.0},
        )
        r1.with_user(manager).user_id = self.seller2
        self.assertEqual(r1.user_id, self.seller2)

    def test_seller_menus_in_inventory(self):
        menus = self.env["ir.ui.menu"].with_user(self.seller)
        visible_ids = menus._visible_menu_ids()
        menu_list = self.env.ref(
            "stock_reservation_sales.stock_sales_reservation_menu_list"
        )
        menu_overview = self.env.ref(
            "stock_reservation_sales.stock_sales_reservation_menu_overview"
        )
        config = self.env.ref("stock.menu_stock_config_settings")
        self.assertIn(self.env.ref("stock.menu_stock_root").id, visible_ids)
        self.assertIn(menu_list.id, visible_ids)
        self.assertNotIn(menu_overview.id, visible_ids)
        self.assertNotIn(config.id, visible_ids)

    def test_inventory_manager_can_create(self):
        manager = self.env["res.users"].create(
            {
                "name": "Inventory manager",
                "login": "inv_manager_reservation",
                "group_ids": [(6, 0, [self.env.ref("stock.group_stock_manager").id])],
            }
        )
        reservation = self._create_reservation(user=manager)
        reservation.action_reserve()
        self.assertEqual(reservation.state, "reserved")

    def test_form_defaults(self):
        with Form(self.env["stock.sales.reservation"]) as form:
            form.product_id = self.product
            form.product_qty = 2.0
            self.assertEqual(form.expiry_duration, "1d")
            self.assertEqual(form.available_qty, 10.0)
