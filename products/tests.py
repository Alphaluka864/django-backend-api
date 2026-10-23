
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from .models import (
    Category,
    Product,
    InventoryMovement,
    Supplier,
    PurchaseOrder,
)


class InventoryAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.staff_user = User.objects.create_user(
            username="inventory_staff",
            password="TestPassword123!",
            is_staff=True,
        )

        self.customer = User.objects.create_user(
            username="inventory_customer",
            password="TestPassword123!",
        )

        self.category = Category.objects.create(name="Food")

        self.product = Product.objects.create(
            name="Sambusa",
            category=self.category,
            price=Decimal("1000.00"),
            stock_quantity=20,
        )

        self.client.force_authenticate(user=self.staff_user)

        self.url = "/api/inventory/movements/"

    def test_stock_in_increases_quantity(self):
        response = self.client.post(
            self.url,
            {
                "product_id": self.product.id,
                "movement_type": "IN",
                "quantity": 10,
                "note": "Restocking",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 30)

        self.assertEqual(
            InventoryMovement.objects.filter(
                product=self.product
            ).count(),
            1,
        )

    def test_stock_out_decreases_quantity(self):
        response = self.client.post(
            self.url,
            {
                "product_id": self.product.id,
                "movement_type": "OUT",
                "quantity": 5,
                "note": "Stock issued",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 15)

    def test_stock_out_cannot_exceed_available_stock(self):
        response = self.client.post(
            self.url,
            {
                "product_id": self.product.id,
                "movement_type": "OUT",
                "quantity": 999,
                "note": "Excessive stock request",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

        self.assertEqual(
            InventoryMovement.objects.filter(
                product=self.product
            ).count(),
            0,
        )

    def test_customer_cannot_adjust_inventory(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.post(
            self.url,
            {
                "product_id": self.product.id,
                "movement_type": "IN",
                "quantity": 10,
                "note": "Unauthorized request",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)



    def test_zero_quantity_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "product_id": self.product.id,
                "movement_type": "IN",
                "quantity": 0,
                "note": "Invalid quantity",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)


    def test_nonexistent_product_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "product_id": 999999,
                "movement_type": "IN",
                "quantity": 5,
                "note": "Invalid product",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_low_stock_endpoint_returns_products_below_threshold(self):
        self.product.stock_quantity = 3
        self.product.save(update_fields=["stock_quantity"])

        response = self.client.get(
            "/api/inventory/low-stock/?threshold=5"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["low_stock_products"][0]["product_id"],
            self.product.id,
        )
    
    def test_inventory_summary_reports_stock_correctly(self):
        InventoryMovement.objects.create(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
            quantity=10,
            note="Test stock in",
            created_by=self.staff_user,
        )

        InventoryMovement.objects.create(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_OUT,
            quantity=5,
            note="Test stock out",
            created_by=self.staff_user,
        )

        response = self.client.get("/api/inventory/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_products"], 1)

        item = response.data["inventory"][0]
        self.assertEqual(item["stock_in_total"], 10)
        self.assertEqual(item["stock_out_total"], 5)
        self.assertEqual(item["current_stock"], 20)


    def test_inventory_summary_requires_staff_access(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get("/api/inventory/summary/")

        self.assertEqual(response.status_code, 403)


    def test_inventory_history_returns_movements(self):
        InventoryMovement.objects.create(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
            quantity=10,
            note="Stock received",
            created_by=self.staff_user,
        )

        response = self.client.get(
            "/api/inventory/movements/history/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["product_name"],
            "Sambusa",
        )

    def test_inventory_history_filters_by_movement_type(self):
        InventoryMovement.objects.create(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
            quantity=10,
            created_by=self.staff_user,
        )
        InventoryMovement.objects.create(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_OUT,
            quantity=5,
            created_by=self.staff_user,
        )

        response = self.client.get(
            "/api/inventory/movements/history/?movement_type=OUT"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["movement_type"],
            "OUT",
        )

    def test_inventory_history_denies_customers(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(
            "/api/inventory/movements/history/"
        )

        self.assertEqual(response.status_code, 403)


    def test_inventory_history_filters_by_product_id(self):
        InventoryMovement.objects.create(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
            quantity=10,
            created_by=self.staff_user,
        )

        response = self.client.get(
            f"/api/inventory/movements/history/?product_id={self.product.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["product_name"],
            "Sambusa",
        )

    def test_inventory_history_invalid_product_id_returns_empty_results(self):
        response = self.client.get(
            "/api/inventory/movements/history/?product_id=999999"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_inventory_history_rejects_invalid_product_id(self):
        response = self.client.get(
            "/api/inventory/movements/history/?product_id=abc"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("product_id", response.data)

    def test_inventory_history_rejects_invalid_movement_type(self):
        response = self.client.get(
            "/api/inventory/movements/history/?movement_type=INVALID"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("movement_type", response.data)

    def test_inventory_history_uses_pagination(self):
        for quantity in range(1, 13):
            InventoryMovement.objects.create(
                product=self.product,
                movement_type=InventoryMovement.MovementType.STOCK_IN,
                quantity=quantity,
                created_by=self.staff_user,
            )

        response = self.client.get(
            "/api/inventory/movements/history/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 12)
        self.assertEqual(len(response.data["results"]), 10)
        self.assertIsNotNone(response.data["next"])

    def test_failed_stock_out_does_not_change_stock_or_create_movement(self):
        initial_stock = self.product.stock_quantity
        initial_movements = InventoryMovement.objects.count()

        response = self.client.post(
            self.url,
            {
                "product_id": self.product.id,
                "movement_type": "OUT",
                "quantity": initial_stock + 1,
                "note": "Should fail",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(
            self.product.stock_quantity,
            initial_stock,
        )
        self.assertEqual(
            InventoryMovement.objects.count(),
            initial_movements,
        )

    def test_inventory_history_does_not_mix_products(self):
        second_product = Product.objects.create(
            name="Juice",
            description="Orange juice",
            price="2000.00",
            stock_quantity=15,
        )

        InventoryMovement.objects.create(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
            quantity=10,
            created_by=self.staff_user,
        )

        InventoryMovement.objects.create(
            product=second_product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
            quantity=7,
            created_by=self.staff_user,
        )

        response = self.client.get(
            f"/api/inventory/movements/history/?product_id={self.product.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["product_name"],
            "Sambusa",
        )



class ProductPermissionTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="product_customer",
            password="test-password-123",
        )

        self.category = Category.objects.create(
            name="Electronics",
        )

        self.product = Product.objects.create(
            name="Keyboard",
            category=self.category,
            price="25000.00",
            stock_quantity=10,
        )

        self.client.force_authenticate(user=self.customer)

    def test_customer_can_list_products(self):
        response = self.client.get("/api/products/")

        self.assertEqual(response.status_code, 200)

    def test_customer_cannot_create_product(self):
        response = self.client.post(
            "/api/products/",
            {
                "name": "Mouse",
                "category_id": self.category.id,
                "price": "15000.00",
                "stock_quantity": 5,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_update_product(self):
        response = self.client.patch(
            f"/api/products/{self.product.id}/",
            {"price": "100.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_delete_product(self):
        response = self.client.delete(
            f"/api/products/{self.product.id}/"
        )

        self.assertEqual(response.status_code, 403)

    def test_staff_can_create_product(self):
        staff_user = User.objects.create_user(
            username="product_staff",
            password="test-password-123",
            is_staff=True,
        )

        self.client.force_authenticate(user=staff_user)

        response = self.client.post(
            "/api/products/",
            {
                "name": "Wireless Mouse",
                "category_id": self.category.id,
                "price": "18000.00",
                "stock_quantity": 8,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Product.objects.filter(name="Wireless Mouse").count(),
            1,
        )



class ProductSearchTests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="Electronics",
        )

        Product.objects.create(
            name="Wireless Keyboard",
            category=self.category,
            price="30000.00",
            stock_quantity=10,
        )

        Product.objects.create(
            name="Wireless Mouse",
            category=self.category,
            price="15000.00",
            stock_quantity=20,
        )

        Product.objects.create(
            name="Office Chair",
            price="80000.00",
            stock_quantity=5,
        )

        staff_user = User.objects.create_user(
            username="search_staff",
            password="test-password-123",
            is_staff=True,
        )
        self.client.force_authenticate(user=staff_user)

    def test_search_finds_products_by_name(self):
        response = self.client.get(
            "/api/products/?search=Keyboard"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["name"],
            "Wireless Keyboard",
        )

    def test_filter_by_category(self):
        response = self.client.get(
            f"/api/products/?category={self.category.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

    def test_order_products_by_price(self):
        response = self.client.get(
            "/api/products/?ordering=price"
        )

        self.assertEqual(response.status_code, 200)
        prices = [
            float(item["price"])
            for item in response.data["results"]
        ]

        self.assertEqual(prices, sorted(prices))



class ProductDetailTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="detail_customer",
            password="test-password-123",
        )

        self.staff_user = User.objects.create_user(
            username="detail_staff",
            password="test-password-123",
            is_staff=True,
        )

        self.product = Product.objects.create(
            name="USB Keyboard",
            price="25000.00",
            stock_quantity=12,
        )

    def test_customer_can_retrieve_product_detail(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(
            f"/api/products/{self.product.id}/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "USB Keyboard")

    def test_customer_cannot_update_product_detail(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.patch(
            f"/api/products/{self.product.id}/",
            {"price": "100.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.product.refresh_from_db()
        self.assertEqual(str(self.product.price), "25000.00")

    def test_staff_can_update_product_detail(self):
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.patch(
            f"/api/products/{self.product.id}/",
            {"price": "28000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.product.refresh_from_db()
        self.assertEqual(str(self.product.price), "28000.00")

    def test_missing_product_returns_404(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get("/api/products/999999/")

        self.assertEqual(response.status_code, 404)



class UserRegistrationTests(APITestCase):
    def test_user_can_register(self):
        response = self.client.post(
            "/api/register/",
            {
                "username": "new_customer",
                "password": "SecureTestPass123!",
                "password2": "SecureTestPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            User.objects.filter(username="new_customer").exists()
        )

        user = User.objects.get(username="new_customer")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_registration_rejects_duplicate_username(self):
        User.objects.create_user(
            username="existing_customer",
            password="SecureTestPass123!",
        )

        response = self.client.post(
            "/api/register/",
            {
                "username": "existing_customer",
                "password": "AnotherSecurePass123!",
                "password2": "AnotherSecurePass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_registration_rejects_mismatched_passwords(self):
        response = self.client.post(
            "/api/register/",
            {
                "username": "mismatch_customer",
                "password": "SecureTestPass123!",
                "password2": "DifferentPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            User.objects.filter(username="mismatch_customer").exists()
        )



class JWTAuthenticationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="jwt_customer",
            password="SecureTestPass123!",
        )

    def test_user_can_obtain_jwt_tokens(self):
        response = self.client.post(
            "/api/token/",
            {
                "username": "jwt_customer",
                "password": "SecureTestPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_invalid_credentials_are_rejected(self):
        response = self.client.post(
            "/api/token/",
            {
                "username": "jwt_customer",
                "password": "WrongPassword123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    def test_refresh_token_returns_new_access_token(self):
        login_response = self.client.post(
            "/api/token/",
            {
                "username": "jwt_customer",
                "password": "SecureTestPass123!",
            },
            format="json",
        )

        refresh_token = login_response.data["refresh"]

        response = self.client.post(
            "/api/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)

    def test_protected_inventory_endpoint_requires_authentication(self):
        response = self.client.get(
            "/api/inventory/movements/history/"
        )

        self.assertEqual(response.status_code, 401)


class InventoryJWTAuthorizationTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="jwt_inventory_customer",
            password="SecureTestPass123!",
        )

        self.staff_user = User.objects.create_user(
            username="jwt_inventory_staff",
            password="SecureTestPass123!",
            is_staff=True,
        )

        self.product = Product.objects.create(
            name="Test Sambusa",
            price="1000.00",
            stock_quantity=20,
        )

    def get_access_token(self, username):
        user = (
            self.customer
            if username == self.customer.username
            else self.staff_user
        )

        response = self.client.post(
            "/api/token/",
            {
                "username": username,
                "password": "SecureTestPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        return response.data["access"]

    def test_customer_jwt_cannot_adjust_inventory(self):
        token = self.get_access_token(self.customer.username)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}"
        )

        response = self.client.post(
            "/api/inventory/movements/",
            {
                "product_id": self.product.id,
                "movement_type": "IN",
                "quantity": 5,
                "note": "Customer attempt",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_staff_jwt_can_adjust_inventory(self):
        token = self.get_access_token(self.staff_user.username)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}"
        )

        response = self.client.post(
            "/api/inventory/movements/",
            {
                "product_id": self.product.id,
                "movement_type": "IN",
                "quantity": 5,
                "note": "Staff stock receipt",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 25)



class CategoryAPITests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="category_customer",
            password="SecureTestPass123!",
        )

        self.staff_user = User.objects.create_user(
            username="category_staff",
            password="SecureTestPass123!",
            is_staff=True,
        )

        self.client.force_authenticate(user=self.customer)

    def test_customer_can_list_categories(self):
        Category.objects.create(
            name="Electronics",
            description="Electronic devices and accessories",
        )

        response = self.client.get("/api/categories/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["name"],
            "Electronics",
        )

    def test_customer_cannot_create_category(self):
        response = self.client.post(
            "/api/categories/",
            {
                "name": "Clothing",
                "description": "Clothes and fashion accessories",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Category.objects.filter(name="Clothing").exists()
        )

    def test_staff_can_create_category(self):
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            "/api/categories/",
            {
                "name": "Clothing",
                "description": "Clothes and fashion accessories",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Category.objects.filter(name="Clothing").exists()
        )

    def test_duplicate_category_name_is_rejected(self):
        Category.objects.create(name="Electronics")

        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            "/api/categories/",
            {"name": "Electronics"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)



class SupplierAPITests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="supplier_customer",
            password="SecureTestPass123!",
        )

        self.staff_user = User.objects.create_user(
            username="supplier_staff",
            password="SecureTestPass123!",
            is_staff=True,
        )

        self.client.force_authenticate(user=self.customer)

        self.supplier_data = {
            "name": "Tanzania Wholesale Ltd",
            "contact_person": "John",
            "email": "sales@example.com",
            "phone": "+255712345678",
            "address": "Arusha, Tanzania",
            "is_active": True,
        }

    def test_customer_can_list_suppliers(self):
        Supplier.objects.create(
            name="Tanzania Wholesale Ltd",
        )

        response = self.client.get("/api/suppliers/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_customer_cannot_create_supplier(self):
        response = self.client.post(
            "/api/suppliers/",
            self.supplier_data,
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Supplier.objects.filter(
                name="Tanzania Wholesale Ltd"
            ).exists()
        )

    def test_staff_can_create_supplier(self):
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            "/api/suppliers/",
            self.supplier_data,
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Supplier.objects.filter(
                name="Tanzania Wholesale Ltd"
            ).exists()
        )

    def test_duplicate_supplier_name_is_rejected(self):
        Supplier.objects.create(
            name="Tanzania Wholesale Ltd",
        )

        self.client.force_authenticate(user=self.staff_user)

        response = self.client.post(
            "/api/suppliers/",
            self.supplier_data,
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_supplier_email_is_rejected(self):
        self.client.force_authenticate(user=self.staff_user)

        data = {
            **self.supplier_data,
            "email": "not-an-email",
        }

        response = self.client.post(
            "/api/suppliers/",
            data,
            format="json",
        )

        self.assertEqual(response.status_code, 400)



class PurchaseOrderAPITests(APITestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="purchase_staff",
            password="SecureTestPass123!",
            is_staff=True,
        )

        self.supplier = Supplier.objects.create(
            name="Purchase Test Supplier",
            is_active=True,
        )

        self.product = Product.objects.create(
            name="Purchase Test Product",
            price=Decimal("1000.00"),
            stock_quantity=20,
        )

        self.client.force_authenticate(user=self.staff_user)

        self.purchase_orders_url = "/api/purchase-orders/"

    def create_purchase_order(self, order_number="PO-TEST-001"):
        response = self.client.post(
            self.purchase_orders_url,
            {
                "order_number": order_number,
                "supplier": self.supplier.id,
                "notes": "Automated test order",
                "items": [
                    {
                        "product": self.product.id,
                        "quantity": 5,
                        "unit_cost": "800.00",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
            msg=str(response.data),
        )

        return response.data["id"]

    def test_staff_can_create_purchase_order(self):
        order_id = self.create_purchase_order()

        order = PurchaseOrder.objects.get(pk=order_id)

        self.assertEqual(
            order.status,
            PurchaseOrder.Status.DRAFT,
        )
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(self.product.stock_quantity, 20)

    def test_draft_order_can_be_marked_ordered(self):
        order_id = self.create_purchase_order()

        response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/order/"
        )

        self.assertEqual(response.status_code, 200)

        order = PurchaseOrder.objects.get(pk=order_id)
        self.assertEqual(
            order.status,
            PurchaseOrder.Status.ORDERED,
        )

    def test_receiving_order_updates_stock_and_creates_movement(self):
        order_id = self.create_purchase_order()

        order_response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/order/"
        )
        self.assertEqual(order_response.status_code, 200)

        response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/receive/"
        )

        self.assertEqual(response.status_code, 200)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 25)

        self.assertEqual(
            InventoryMovement.objects.filter(
                product=self.product,
                movement_type="IN",
                note=f"Received against PO-TEST-001",
            ).count(),
            1,
        )

        order = PurchaseOrder.objects.get(pk=order_id)
        self.assertEqual(
            order.status,
            PurchaseOrder.Status.RECEIVED,
        )
        self.assertIsNotNone(order.received_at)

    def test_order_cannot_be_received_twice(self):
        order_id = self.create_purchase_order()

        self.client.post(
            f"{self.purchase_orders_url}{order_id}/order/"
        )

        first_response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/receive/"
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/receive/"
        )
        self.assertEqual(second_response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 25)

        self.assertEqual(
            InventoryMovement.objects.filter(
                product=self.product,
                note="Received against PO-TEST-001",
            ).count(),
            1,
        )

    def test_draft_order_can_be_cancelled_without_changing_stock(self):
        order_id = self.create_purchase_order()

        response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/cancel/"
        )

        self.assertEqual(response.status_code, 200)

        order = PurchaseOrder.objects.get(pk=order_id)
        self.assertEqual(
            order.status,
            PurchaseOrder.Status.CANCELLED,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

    def test_cancelled_order_cannot_be_received(self):
        order_id = self.create_purchase_order()

        cancel_response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/cancel/"
        )
        self.assertEqual(cancel_response.status_code, 200)

        receive_response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/receive/"
        )
        self.assertEqual(receive_response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

        self.assertFalse(
            InventoryMovement.objects.filter(
                product=self.product,
                note="Received against PO-TEST-001",
            ).exists()
        )

    def test_received_order_cannot_be_cancelled(self):
        order_id = self.create_purchase_order()

        self.client.post(
            f"{self.purchase_orders_url}{order_id}/order/"
        )

        receive_response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/receive/"
        )
        self.assertEqual(receive_response.status_code, 200)

        cancel_response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/cancel/"
        )
        self.assertEqual(cancel_response.status_code, 400)

        order = PurchaseOrder.objects.get(pk=order_id)
        self.assertEqual(
            order.status,
            PurchaseOrder.Status.RECEIVED,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 25)

    def test_unauthenticated_user_cannot_cancel_order(self):
        order_id = self.create_purchase_order()

        self.client.force_authenticate(user=None)

        response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/cancel/"
        )

        self.assertEqual(response.status_code, 401)

    
    def test_invalid_created_after_returns_400(self):
        response = self.client.get(
            self.purchase_orders_url,
            {"created_after": "not-a-date"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("created_after", response.data)

    def test_invalid_created_before_returns_400(self):
        response = self.client.get(
            self.purchase_orders_url,
            {"created_before": "not-a-date"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("created_before", response.data)

    def test_valid_date_range_returns_matching_orders(self):
        order_id = self.create_purchase_order()

        response = self.client.get(
            self.purchase_orders_url,
            {
                "created_after": "2026-10-01",
                "created_before": "2026-10-31",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["id"],
            order_id,
        )
    
    def test_non_numeric_supplier_filter_returns_400(self):
        response = self.client.get(
            self.purchase_orders_url,
            {"supplier": "abc"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("supplier", response.data)

    def test_nonexistent_supplier_filter_returns_400(self):
        response = self.client.get(
            self.purchase_orders_url,
            {"supplier": "999999"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("supplier", response.data)

    def test_reversed_date_range_returns_400(self):
        response = self.client.get(
            self.purchase_orders_url,
            {
                "created_after": "2026-10-31",
                "created_before": "2026-10-01",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("date_range", response.data)
    
    def test_staff_can_view_purchase_order_summary(self):
        self.create_purchase_order()

        response = self.client.get(
            "/api/purchase-orders/summary/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_orders"], 1)
        self.assertEqual(response.data["draft_orders"], 1)
        self.assertEqual(response.data["ordered_orders"], 0)
        self.assertEqual(response.data["received_orders"], 0)
        self.assertEqual(response.data["cancelled_orders"], 0)
        self.assertEqual(response.data["total_value"], "4000.00")

    def test_non_staff_user_cannot_view_purchase_order_summary(self):
        regular_user = User.objects.create_user(
            username="regular_summary_user",
            password="SecureTestPass123!",
            is_staff=False,
        )

        self.client.force_authenticate(user=regular_user)

        response = self.client.get(
            "/api/purchase-orders/summary/"
        )

        self.assertEqual(response.status_code, 403)
