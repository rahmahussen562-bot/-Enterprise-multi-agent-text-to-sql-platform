"""
Unit tests for core.auth corporate authentication and RBAC table whitelists.
"""
import unittest
from core.auth import authenticate, filter_authorized_tables, is_table_authorized


class TestCorporateAuth(unittest.TestCase):
    def test_sales_analyst_authentication(self):
        user = authenticate("sales_analyst", "Sales@2026!")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "sales_analyst")
        self.assertEqual(user.role_title, "Sales Analyst")
        self.assertEqual(user.scope, "Commercial Domain")
        self.assertIn("Customer", user.authorized_tables)
        self.assertIn("Invoice", user.authorized_tables)
        self.assertIn("InvoiceLine", user.authorized_tables)
        self.assertNotIn("Track", user.authorized_tables)

    def test_inventory_lead_authentication(self):
        user = authenticate("inventory_lead", "Ops@2026!")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "inventory_lead")
        self.assertEqual(user.role_title, "Inventory Lead")
        self.assertEqual(user.scope, "Operational & Catalog Domain")
        self.assertIn("Track", user.authorized_tables)
        self.assertIn("Artist", user.authorized_tables)
        self.assertNotIn("Invoice", user.authorized_tables)

    def test_invalid_credentials_rejected(self):
        self.assertIsNone(authenticate("sales_analyst", "WrongPassword!"))
        self.assertIsNone(authenticate("unknown_user", "AnyPassword!"))

    def test_table_authorization_checks(self):
        sales_user = authenticate("sales_analyst", "Sales@2026!")
        self.assertTrue(is_table_authorized(sales_user, "Customer"))
        self.assertTrue(is_table_authorized(sales_user, "[Customer]"))
        self.assertTrue(is_table_authorized(sales_user, "dbo.Invoice"))
        self.assertFalse(is_table_authorized(sales_user, "Track"))
        self.assertFalse(is_table_authorized(sales_user, "[Album]"))

        inv_user = authenticate("inventory_lead", "Ops@2026!")
        self.assertTrue(is_table_authorized(inv_user, "Track"))
        self.assertTrue(is_table_authorized(inv_user, "[Artist]"))
        self.assertFalse(is_table_authorized(inv_user, "Customer"))
        self.assertFalse(is_table_authorized(inv_user, "InvoiceLine"))

    def test_filter_authorized_tables(self):
        sales_user = authenticate("sales_analyst", "Sales@2026!")
        all_tables = ["Customer", "Invoice", "Track", "Album", "InvoiceLine"]
        filtered = filter_authorized_tables(sales_user, all_tables)
        self.assertEqual(sorted(filtered), sorted(["Customer", "Invoice", "InvoiceLine"]))

    def test_allowed_tables_property(self):
        sales_user = authenticate("sales_analyst", "Sales@2026!")
        self.assertEqual(sales_user.allowed_tables, ["Customer", "Invoice", "InvoiceLine"])
        inv_user = authenticate("inventory_lead", "Ops@2026!")
        self.assertEqual(inv_user.allowed_tables, ["Track", "Album", "Artist", "Genre", "MediaType"])


if __name__ == "__main__":
    unittest.main()
