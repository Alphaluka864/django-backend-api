
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
    ProductAuditLog,
)
from django.db import IntegrityError, transaction
from django.core.cache import cache
from .models import (
    SellerProfile,
    CustomerOrder,
    CustomerOrderItem,
    Cart,
    CartItem,
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

    def test_database_rejects_zero_quantity_movement(self):
        movement_count = InventoryMovement.objects.count()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InventoryMovement.objects.create(
                    product=self.product,
                    movement_type="IN",
                    quantity=0,
                    note="Invalid zero quantity",
                    created_by=self.staff_user,
                )

        self.assertEqual(
            InventoryMovement.objects.count(),
            movement_count,
        )

    def test_database_rejects_negative_quantity_movement(self):
        movement_count = InventoryMovement.objects.count()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InventoryMovement.objects.create(
                    product=self.product,
                    movement_type="IN",
                    quantity=-5,
                    note="Invalid negative quantity",
                    created_by=self.staff_user,
                )

        self.assertEqual(
            InventoryMovement.objects.count(),
            movement_count,
        )

    def test_database_rejects_invalid_movement_type(self):
        movement_count = InventoryMovement.objects.count()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InventoryMovement.objects.create(
                    product=self.product,
                    movement_type="BAD",
                    quantity=5,
                    note="Invalid movement type",
                    created_by=self.staff_user,
                )

        self.assertEqual(
            InventoryMovement.objects.count(),
            movement_count,
        )

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


    def test_inventory_summary_uses_constant_query_count(self):
        Product.objects.create(
            name="Pilau",
            description="Rice dish",
            price=Decimal("3000.00"),
            stock_quantity=15,
            category=self.category,
        )

        Product.objects.create(
            name="Chapati",
            description="Flatbread",
            price=Decimal("1000.00"),
            stock_quantity=8,
            category=self.category,
        )

        with self.assertNumQueries(2):
            response = self.client.get("/api/inventory/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_products"], 3)
        self.assertEqual(len(response.data["inventory"]), 3)

        products_by_id = {
            item["product_id"]: item
            for item in response.data["inventory"]
        }

        self.assertEqual(
            products_by_id[self.product.id]["stock_in_total"],
            0,
        )
        self.assertEqual(
            products_by_id[self.product.id]["stock_out_total"],
            0,
        )
        self.assertEqual(
            products_by_id[self.product.id]["current_stock"],
            20,
        )



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

        product = Product.objects.get(name="Wireless Mouse")
        self.assertEqual(product.stock_quantity, 0)

        self.assertFalse(
            InventoryMovement.objects.filter(product=product).exists()
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


    def test_staff_cannot_change_stock_directly(self):
        self.client.force_authenticate(user=self.staff_user)

        original_stock = self.product.stock_quantity
        original_movement_count = InventoryMovement.objects.filter(
            product=self.product
        ).count()

        response = self.client.patch(
            f"/api/products/{self.product.id}/",
            {"stock_quantity": 999},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, original_stock)

        self.assertEqual(
            InventoryMovement.objects.filter(
                product=self.product
            ).count(),
            original_movement_count,
        )


    def test_missing_product_returns_404(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get("/api/products/999999/")

        self.assertEqual(response.status_code, 404)



class UserRegistrationTests(APITestCase):
    def setUp(self):
        cache.clear()

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
    def test_registration_rejects_common_password(self):
        response = self.client.post(
            "/api/register/",
            {
                "username": "weak_password_user",
                "password": "password",
                "password2": "password",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            User.objects.filter(
                username="weak_password_user"
            ).exists()
        )

    def test_registration_rejects_numeric_only_password(self):
        response = self.client.post(
            "/api/register/",
            {
                "username": "numeric_password_user",
                "password": "1234567890",
                "password2": "1234567890",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            User.objects.filter(
                username="numeric_password_user"
            ).exists()
        )
    def test_registration_rate_limit(self):
        for i in range(4):
            response = self.client.post(
                "/api/register/",
                {
                    "username": f"throttle_customer_{i}",
                    "password": "SecureTestPass123!",
                    "password2": "SecureTestPass123!",
                },
                format="json",
            )

            if i < 3:
                self.assertEqual(response.status_code, 201)
            else:
                self.assertEqual(response.status_code, 429)



class JWTAuthenticationTests(APITestCase):
    def setUp(self):
        cache.clear()

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
    def test_blacklisted_refresh_token_cannot_be_reused(self):
        login_response = self.client.post(
            "/api/token/",
            {
                "username": "jwt_customer",
                "password": "SecureTestPass123!",
            },
            format="json",
        )

        self.assertEqual(login_response.status_code, 200)
        refresh_token = login_response.data["refresh"]

        logout_response = self.client.post(
            "/api/token/blacklist/",
            {"refresh": refresh_token},
            format="json",
        )

        self.assertEqual(logout_response.status_code, 200)

        refresh_response = self.client.post(
            "/api/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )

        self.assertEqual(refresh_response.status_code, 401)

    def test_protected_inventory_endpoint_requires_authentication(self):
        response = self.client.get(
            "/api/inventory/movements/history/"
        )

        self.assertEqual(response.status_code, 401)
    def test_login_rate_limit(self):
        for i in range(6):
            response = self.client.post(
                "/api/token/",
                {
                    "username": f"unknown_user_{i}",
                    "password": "WrongPassword123!",
                },
                format="json",
            )

            if i < 5:
                self.assertEqual(response.status_code, 401)
            else:
                self.assertEqual(response.status_code, 429)


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
    def test_customer_cannot_list_purchase_orders(self):
        customer = User.objects.create_user(
            username="po_security_customer",
            password="SecureTestPass123!",
        )
        self.client.force_authenticate(user=customer)

        response = self.client.get(self.purchase_orders_url)

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_create_purchase_orders(self):
        customer = User.objects.create_user(
            username="po_create_customer",
            password="SecureTestPass123!",
        )
        self.client.force_authenticate(user=customer)

        response = self.client.post(
            self.purchase_orders_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_access_purchase_order_detail(self):
        order_id = self.create_purchase_order()

        customer = User.objects.create_user(
            username="po_detail_customer",
            password="SecureTestPass123!",
        )
        self.client.force_authenticate(user=customer)

        response = self.client.get(
            f"{self.purchase_orders_url}{order_id}/"
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_mark_purchase_order_as_ordered(self):
        order_id = self.create_purchase_order()

        customer = User.objects.create_user(
            username="po_order_customer",
            password="SecureTestPass123!",
        )
        self.client.force_authenticate(user=customer)

        response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/order/"
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_receive_purchase_order(self):
        order_id = self.create_purchase_order()

        customer = User.objects.create_user(
            username="po_receive_customer",
            password="SecureTestPass123!",
        )
        self.client.force_authenticate(user=customer)

        response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/receive/"
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_cancel_purchase_order(self):
        order_id = self.create_purchase_order()

        customer = User.objects.create_user(
            username="po_cancel_customer",
            password="SecureTestPass123!",
        )
        self.client.force_authenticate(user=customer)

        response = self.client.post(
            f"{self.purchase_orders_url}{order_id}/cancel/"
        )

        self.assertEqual(response.status_code, 403)


class ProductWorkflowAuditTests(APITestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="workflow_staff",
            password="TestPassword123!",
            is_staff=True,
        )

        self.customer = User.objects.create_user(
            username="workflow_customer",
            password="TestPassword123!",
            is_staff=False,
        )

        self.category = Category.objects.create(name="Workflow Food")

        self.product = Product.objects.create(
            name="Workflow Sambusa",
            category=self.category,
            price=Decimal("1500.00"),
            stock_quantity=10,
            status=Product.Status.DRAFT,
        )

        self.client.force_authenticate(user=self.staff_user)

    def test_submit_review_creates_audit_record(self):
        response = self.client.post(
            f"/api/products/{self.product.id}/submit-review/"
        )

        self.assertEqual(response.status_code, 200)

        self.product.refresh_from_db()

        self.assertEqual(
            self.product.status,
            Product.Status.UNDER_REVIEW,
        )

        audit = ProductAuditLog.objects.get(product=self.product)

        self.assertEqual(audit.actor, self.staff_user)
        self.assertEqual(audit.action, ProductAuditLog.Action.SUBMITTED)
        self.assertEqual(audit.previous_status, Product.Status.DRAFT)
        self.assertEqual(
            audit.new_status,
            Product.Status.UNDER_REVIEW,
        )

    def test_invalid_transition_does_not_create_audit_record(self):
        response = self.client.post(
            f"/api/products/{self.product.id}/approve/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            ProductAuditLog.objects.filter(product=self.product).count(),
            0,
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.DRAFT)

    def test_customer_cannot_access_audit_logs(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get("/api/product-audit-logs/")

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_access_audit_logs(self):
        self.client.force_authenticate(user=None)

        response = self.client.get("/api/product-audit-logs/")

        self.assertEqual(response.status_code, 401)

    def test_audit_log_endpoint_filters_by_action(self):
        ProductAuditLog.objects.create(
            product=self.product,
            actor=self.staff_user,
            action=ProductAuditLog.Action.SUBMITTED,
            previous_status=Product.Status.DRAFT,
            new_status=Product.Status.UNDER_REVIEW,
        )

        response = self.client.get(
            "/api/product-audit-logs/?action=SUBMITTED"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["action"],
            "SUBMITTED",
        )

    def test_audit_log_endpoint_filters_by_product(self):
        ProductAuditLog.objects.create(
            product=self.product,
            actor=self.staff_user,
            action=ProductAuditLog.Action.SUBMITTED,
            previous_status=Product.Status.DRAFT,
            new_status=Product.Status.UNDER_REVIEW,
        )

        response = self.client.get(
            f"/api/product-audit-logs/?product={self.product.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_approval_creates_correct_audit_record(self):
        self.product.status = Product.Status.UNDER_REVIEW
        self.product.save(update_fields=["status", "updated_at"])

        response = self.client.post(
            f"/api/products/{self.product.id}/approve/"
        )

        self.assertEqual(response.status_code, 200)

        audit = ProductAuditLog.objects.get(product=self.product)

        self.assertEqual(audit.action, ProductAuditLog.Action.APPROVED)
        self.assertEqual(
            audit.previous_status,
            Product.Status.UNDER_REVIEW,
        )
        self.assertEqual(audit.new_status, Product.Status.PUBLISHED)
        self.assertEqual(audit.actor, self.staff_user)

    def test_return_to_draft_creates_correct_audit_record(self):
        self.product.status = Product.Status.UNDER_REVIEW
        self.product.save(update_fields=["status", "updated_at"])

        response = self.client.post(
            f"/api/products/{self.product.id}/return-to-draft/"
        )

        self.assertEqual(response.status_code, 200)

        audit = ProductAuditLog.objects.get(product=self.product)

        self.assertEqual(audit.action, ProductAuditLog.Action.RETURNED)
        self.assertEqual(
            audit.previous_status,
            Product.Status.UNDER_REVIEW,
        )
        self.assertEqual(audit.new_status, Product.Status.DRAFT)

    def test_product_audit_history_returns_only_requested_product(self):
        other_product = Product.objects.create(
            name="Other Workflow Product",
            category=self.category,
            price=Decimal("2000.00"),
            status=Product.Status.DRAFT,
        )

        ProductAuditLog.objects.create(
            product=self.product,
            actor=self.staff_user,
            action=ProductAuditLog.Action.SUBMITTED,
            previous_status=Product.Status.DRAFT,
            new_status=Product.Status.UNDER_REVIEW,
        )

        ProductAuditLog.objects.create(
            product=other_product,
            actor=self.staff_user,
            action=ProductAuditLog.Action.SUBMITTED,
            previous_status=Product.Status.DRAFT,
            new_status=Product.Status.UNDER_REVIEW,
        )

        response = self.client.get(
            f"/api/products/{self.product.id}/audit-history/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["product"],
            self.product.id,
        )

    def test_product_audit_history_orders_newest_first(self):
        older = ProductAuditLog.objects.create(
            product=self.product,
            actor=self.staff_user,
            action=ProductAuditLog.Action.SUBMITTED,
            previous_status=Product.Status.DRAFT,
            new_status=Product.Status.UNDER_REVIEW,
        )

        newer = ProductAuditLog.objects.create(
            product=self.product,
            actor=self.staff_user,
            action=ProductAuditLog.Action.APPROVED,
            previous_status=Product.Status.UNDER_REVIEW,
            new_status=Product.Status.PUBLISHED,
        )

        response = self.client.get(
            f"/api/products/{self.product.id}/audit-history/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            response.data["results"][0]["id"],
            newer.id,
        )
        self.assertEqual(
            response.data["results"][1]["id"],
            older.id,
        )

    def test_customer_cannot_access_product_audit_history(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(
            f"/api/products/{self.product.id}/audit-history/"
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_access_product_audit_history(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(
            f"/api/products/{self.product.id}/audit-history/"
        )

        self.assertEqual(response.status_code, 401)


class SellerDashboardSummaryAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()

        self.staff_user = User.objects.create_user(
            username="dashboard_staff",
            password="DashboardTest123!",
            is_staff=True,
        )

        self.customer = User.objects.create_user(
            username="dashboard_customer",
            password="DashboardTest123!",
        )

        self.supplier = Supplier.objects.create(
            name="Dashboard Supplier",
        )

        self.category = Category.objects.create(
            name="Dashboard Category",
        )

        self.published_product = Product.objects.create(
            name="Dashboard Published Product",
            category=self.category,
            price=Decimal("1000.00"),
            stock_quantity=10,
            status=Product.Status.PUBLISHED,
        )

        self.draft_product = Product.objects.create(
            name="Dashboard Draft Product",
            category=self.category,
            price=Decimal("2000.00"),
            stock_quantity=2,
            status=Product.Status.DRAFT,
        )

        self.review_product = Product.objects.create(
            name="Dashboard Review Product",
            category=self.category,
            price=Decimal("3000.00"),
            stock_quantity=0,
            status=Product.Status.UNDER_REVIEW,
        )

        self.url = "/api/dashboard/summary/"
        self.client.force_authenticate(user=self.staff_user)

    def test_dashboard_returns_correct_product_and_inventory_summary(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["products"],
            {
                "total": 3,
                "published": 1,
                "drafts": 1,
                "under_review": 1,
            },
        )

        self.assertEqual(
            response.data["inventory"]["total_units_in_stock"],
            12,
        )

        self.assertEqual(
            response.data["inventory"]["low_stock_products"],
            2,
        )

        self.assertEqual(
            response.data["inventory"]["low_stock_threshold"],
            5,
        )

    def test_dashboard_returns_purchase_order_summary(self):
        PurchaseOrder.objects.create(
            order_number="DASH-PO-001",
            supplier=self.supplier,
            created_by=self.staff_user,
            status=PurchaseOrder.Status.DRAFT,
        )

        PurchaseOrder.objects.create(
            order_number="DASH-PO-002",
            supplier=self.supplier,
            created_by=self.staff_user,
            status=PurchaseOrder.Status.RECEIVED,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["purchase_orders"],
            {
                "total": 2,
                "draft": 1,
                "ordered": 0,
                "received": 1,
                "cancelled": 0,
            },
        )

    def test_dashboard_returns_recent_product_audit_activity(self):
        ProductAuditLog.objects.create(
            product=self.published_product,
            actor=self.staff_user,
            action=ProductAuditLog.Action.APPROVED,
            previous_status=Product.Status.UNDER_REVIEW,
            new_status=Product.Status.PUBLISHED,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["recent_activity"]), 1)

        activity = response.data["recent_activity"][0]

        self.assertEqual(
            activity["product"],
            self.published_product.id,
        )
        self.assertEqual(
            activity["action"],
            ProductAuditLog.Action.APPROVED,
        )

    def test_customer_cannot_access_dashboard_summary(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_access_dashboard_summary(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)



class SellerProductOwnershipTests(APITestCase):
    def setUp(self):
        self.seller_one = User.objects.create_user(
            username="seller_one",
            password="SecureTestPass123!",
        )
        self.seller_two = User.objects.create_user(
            username="seller_two",
            password="SecureTestPass123!",
        )
        self.pending_seller = User.objects.create_user(
            username="pending_seller",
            password="SecureTestPass123!",
        )
        self.suspended_seller = User.objects.create_user(
            username="suspended_seller",
            password="SecureTestPass123!",
        )
        self.customer = User.objects.create_user(
            username="regular_customer",
            password="SecureTestPass123!",
        )
        self.admin = User.objects.create_user(
            username="seller_test_admin",
            password="SecureTestPass123!",
            is_staff=True,
        )

        self.profile_one = SellerProfile.objects.create(
            user=self.seller_one,
            business_name="Seller One Store",
            status=SellerProfile.Status.APPROVED,
        )
        self.profile_two = SellerProfile.objects.create(
            user=self.seller_two,
            business_name="Seller Two Store",
            status=SellerProfile.Status.APPROVED,
        )
        SellerProfile.objects.create(
            user=self.pending_seller,
            business_name="Pending Store",
            status=SellerProfile.Status.PENDING,
        )
        SellerProfile.objects.create(
            user=self.suspended_seller,
            business_name="Suspended Store",
            status=SellerProfile.Status.SUSPENDED,
        )

        self.category = Category.objects.create(
            name="Seller Test Electronics",
        )

        self.product_one = Product.objects.create(
            owner=self.seller_one,
            name="Seller One Keyboard",
            category=self.category,
            price="25000.00",
            stock_quantity=0,
            status=Product.Status.DRAFT,
        )
        self.product_two = Product.objects.create(
            owner=self.seller_two,
            name="Seller Two Mouse",
            category=self.category,
            price="15000.00",
            stock_quantity=0,
            status=Product.Status.DRAFT,
        )

    def product_payload(self, name="New Seller Product"):
        return {
            "name": name,
            "description": "Created by a marketplace seller",
            "category_id": self.category.id,
            "price": "12000.00",
            "stock_quantity": 50,
            "status": "PUBLISHED",
        }

    def test_approved_seller_creates_owned_draft(self):
        self.client.force_authenticate(user=self.seller_one)

        response = self.client.post(
            "/api/products/",
            self.product_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        product = Product.objects.get(name="New Seller Product")
        self.assertEqual(product.owner, self.seller_one)
        self.assertEqual(product.status, Product.Status.DRAFT)
        self.assertEqual(product.stock_quantity, 0)

    def test_seller_cannot_update_another_sellers_product(self):
        self.client.force_authenticate(user=self.seller_one)

        response = self.client.patch(
            f"/api/products/{self.product_two.id}/",
            {"price": "100.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.product_two.refresh_from_db()
        self.assertEqual(str(self.product_two.price), "15000.00")

    def test_seller_cannot_delete_another_sellers_product(self):
        self.client.force_authenticate(user=self.seller_one)

        response = self.client.delete(
            f"/api/products/{self.product_two.id}/",
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            Product.objects.filter(pk=self.product_two.pk).exists()
        )

    def test_approved_seller_can_manage_own_draft(self):
        self.client.force_authenticate(user=self.seller_one)

        response = self.client.get(
            f"/api/products/{self.product_one.id}/?manage=true"
        )

        self.assertEqual(response.status_code, 200)

    def test_pending_seller_cannot_create_product(self):
        self.client.force_authenticate(user=self.pending_seller)

        response = self.client.post(
            "/api/products/",
            self.product_payload("Pending Seller Product"),
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_suspended_seller_cannot_create_product(self):
        self.client.force_authenticate(user=self.suspended_seller)

        response = self.client.post(
            "/api/products/",
            self.product_payload("Suspended Seller Product"),
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_create_product(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.post(
            "/api/products/",
            self.product_payload("Customer Product"),
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_another_sellers_product(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            f"/api/products/{self.product_two.id}/",
            {"price": "18000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.product_two.refresh_from_db()
        self.assertEqual(str(self.product_two.price), "18000.00")



class SellerProductWorkflowSecurityTests(APITestCase):
    def setUp(self):
        self.seller_one = User.objects.create_user(
            username="workflow_seller_one",
            password="SecureTestPass123!",
        )
        self.seller_two = User.objects.create_user(
            username="workflow_seller_two",
            password="SecureTestPass123!",
        )
        self.pending_seller = User.objects.create_user(
            username="workflow_pending_seller",
            password="SecureTestPass123!",
        )
        self.suspended_seller = User.objects.create_user(
            username="workflow_suspended_seller",
            password="SecureTestPass123!",
        )
        self.admin = User.objects.create_user(
            username="workflow_admin",
            password="SecureTestPass123!",
            is_staff=True,
        )

        SellerProfile.objects.create(
            user=self.seller_one,
            business_name="Workflow Seller One",
            status=SellerProfile.Status.APPROVED,
        )
        SellerProfile.objects.create(
            user=self.seller_two,
            business_name="Workflow Seller Two",
            status=SellerProfile.Status.APPROVED,
        )
        SellerProfile.objects.create(
            user=self.pending_seller,
            business_name="Workflow Pending Seller",
            status=SellerProfile.Status.PENDING,
        )
        SellerProfile.objects.create(
            user=self.suspended_seller,
            business_name="Workflow Suspended Seller",
            status=SellerProfile.Status.SUSPENDED,
        )

        self.category = Category.objects.create(
            name="Workflow Security Category",
        )

        self.own_product = Product.objects.create(
            owner=self.seller_one,
            name="Seller One Draft",
            category=self.category,
            price=Decimal("12000.00"),
            stock_quantity=0,
            status=Product.Status.DRAFT,
        )

        self.other_product = Product.objects.create(
            owner=self.seller_two,
            name="Seller Two Draft",
            category=self.category,
            price=Decimal("15000.00"),
            stock_quantity=0,
            status=Product.Status.DRAFT,
        )

    def test_approved_seller_can_submit_own_draft(self):
        self.client.force_authenticate(user=self.seller_one)

        response = self.client.post(
            f"/api/products/{self.own_product.id}/submit-review/"
        )

        self.assertEqual(response.status_code, 200)

        self.own_product.refresh_from_db()
        self.assertEqual(
            self.own_product.status,
            Product.Status.UNDER_REVIEW,
        )

        audit = ProductAuditLog.objects.get(
            product=self.own_product,
        )
        self.assertEqual(audit.actor, self.seller_one)
        self.assertEqual(
            audit.action,
            ProductAuditLog.Action.SUBMITTED,
        )
        self.assertEqual(audit.previous_status, Product.Status.DRAFT)
        self.assertEqual(
            audit.new_status,
            Product.Status.UNDER_REVIEW,
        )

    def test_seller_cannot_submit_another_sellers_product(self):
        self.client.force_authenticate(user=self.seller_one)

        response = self.client.post(
            f"/api/products/{self.other_product.id}/submit-review/"
        )

        self.assertEqual(response.status_code, 403)

        self.other_product.refresh_from_db()
        self.assertEqual(
            self.other_product.status,
            Product.Status.DRAFT,
        )
        self.assertFalse(
            ProductAuditLog.objects.filter(
                product=self.other_product,
            ).exists()
        )

    def test_pending_seller_cannot_submit_product(self):
        self.client.force_authenticate(user=self.pending_seller)

        response = self.client.post(
            f"/api/products/{self.own_product.id}/submit-review/"
        )

        self.assertEqual(response.status_code, 403)

    def test_suspended_seller_cannot_submit_product(self):
        self.client.force_authenticate(user=self.suspended_seller)

        response = self.client.post(
            f"/api/products/{self.own_product.id}/submit-review/"
        )

        self.assertEqual(response.status_code, 403)

    def test_seller_cannot_approve_product(self):
        self.own_product.status = Product.Status.UNDER_REVIEW
        self.own_product.save(update_fields=["status", "updated_at"])

        self.client.force_authenticate(user=self.seller_one)

        response = self.client.post(
            f"/api/products/{self.own_product.id}/approve/"
        )

        self.assertEqual(response.status_code, 403)

        self.own_product.refresh_from_db()
        self.assertEqual(
            self.own_product.status,
            Product.Status.UNDER_REVIEW,
        )

    def test_seller_cannot_return_product_to_draft(self):
        self.own_product.status = Product.Status.UNDER_REVIEW
        self.own_product.save(update_fields=["status", "updated_at"])

        self.client.force_authenticate(user=self.seller_one)

        response = self.client.post(
            f"/api/products/{self.own_product.id}/return-to-draft/"
        )

        self.assertEqual(response.status_code, 403)

        self.own_product.refresh_from_db()
        self.assertEqual(
            self.own_product.status,
            Product.Status.UNDER_REVIEW,
        )

    def test_admin_can_approve_submitted_product(self):
        self.own_product.status = Product.Status.UNDER_REVIEW
        self.own_product.save(update_fields=["status", "updated_at"])

        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            f"/api/products/{self.own_product.id}/approve/"
        )

        self.assertEqual(response.status_code, 200)

        self.own_product.refresh_from_db()
        self.assertEqual(
            self.own_product.status,
            Product.Status.PUBLISHED,
        )

        audit = ProductAuditLog.objects.get(
            product=self.own_product,
            action=ProductAuditLog.Action.APPROVED,
        )
        self.assertEqual(audit.actor, self.admin)

    def test_seller_cannot_submit_same_product_twice(self):
        self.client.force_authenticate(user=self.seller_one)

        first_response = self.client.post(
            f"/api/products/{self.own_product.id}/submit-review/"
        )
        second_response = self.client.post(
            f"/api/products/{self.own_product.id}/submit-review/"
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(
            ProductAuditLog.objects.filter(
                product=self.own_product,
            ).count(),
            1,
        )



class SellerDashboardIsolationTests(APITestCase):
    def setUp(self):
        self.seller_one = User.objects.create_user(
            username="dashboard_seller_one",
            password="SecureTestPass123!",
        )
        self.seller_two = User.objects.create_user(
            username="dashboard_seller_two",
            password="SecureTestPass123!",
        )
        self.pending_seller = User.objects.create_user(
            username="dashboard_pending_seller",
            password="SecureTestPass123!",
        )
        self.suspended_seller = User.objects.create_user(
            username="dashboard_suspended_seller",
            password="SecureTestPass123!",
        )
        self.customer = User.objects.create_user(
            username="dashboard_regular_customer",
            password="SecureTestPass123!",
        )
        self.admin = User.objects.create_user(
            username="dashboard_admin",
            password="SecureTestPass123!",
            is_staff=True,
        )

        SellerProfile.objects.create(
            user=self.seller_one,
            business_name="Dashboard Isolation Store One",
            status=SellerProfile.Status.APPROVED,
        )
        SellerProfile.objects.create(
            user=self.seller_two,
            business_name="Dashboard Isolation Store Two",
            status=SellerProfile.Status.APPROVED,
        )
        SellerProfile.objects.create(
            user=self.pending_seller,
            business_name="Dashboard Pending Store",
            status=SellerProfile.Status.PENDING,
        )
        SellerProfile.objects.create(
            user=self.suspended_seller,
            business_name="Dashboard Suspended Store",
            status=SellerProfile.Status.SUSPENDED,
        )

        self.category = Category.objects.create(
            name="Dashboard Isolation Category",
        )
        self.url = "/api/seller/dashboard/"

        Product.objects.create(
            owner=self.seller_one,
            name="Seller One Published",
            category=self.category,
            price=Decimal("1000.00"),
            stock_quantity=8,
            status=Product.Status.PUBLISHED,
        )
        Product.objects.create(
            owner=self.seller_one,
            name="Seller One Draft",
            category=self.category,
            price=Decimal("2000.00"),
            stock_quantity=2,
            status=Product.Status.DRAFT,
        )
        Product.objects.create(
            owner=self.seller_one,
            name="Seller One Under Review",
            category=self.category,
            price=Decimal("3000.00"),
            stock_quantity=0,
            status=Product.Status.UNDER_REVIEW,
        )
        Product.objects.create(
            owner=self.seller_two,
            name="Seller Two Published",
            category=self.category,
            price=Decimal("4000.00"),
            stock_quantity=50,
            status=Product.Status.PUBLISHED,
        )

    def test_dashboard_counts_only_own_products(self):
        self.client.force_authenticate(user=self.seller_one)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["business_name"],
            "Dashboard Isolation Store One",
        )
        self.assertEqual(
            response.data["products"],
            {
                "total": 3,
                "published": 1,
                "drafts": 1,
                "under_review": 1,
            },
        )
        self.assertEqual(
            response.data["inventory"]["total_units_in_stock"],
            10,
        )
        self.assertEqual(
            response.data["inventory"]["low_stock_products"],
            2,
        )

    def test_dashboard_does_not_include_another_sellers_stock(self):
        self.client.force_authenticate(user=self.seller_one)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(
            response.data["inventory"]["total_units_in_stock"],
            60,
        )
        self.assertEqual(
            response.data["inventory"]["total_units_in_stock"],
            10,
        )

    def test_second_seller_gets_separate_summary(self):
        self.client.force_authenticate(user=self.seller_two)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["products"]["total"],
            1,
        )
        self.assertEqual(
            response.data["products"]["published"],
            1,
        )
        self.assertEqual(
            response.data["inventory"]["total_units_in_stock"],
            50,
        )
        self.assertEqual(
            response.data["inventory"]["low_stock_products"],
            0,
        )

    def test_pending_seller_is_denied(self):
        self.client.force_authenticate(user=self.pending_seller)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_suspended_seller_is_denied(self):
        self.client.force_authenticate(user=self.suspended_seller)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_regular_customer_is_denied(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_denied(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_admin_uses_global_dashboard_instead(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

class CustomerOrderAPITests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="checkout_customer",
            password="CustomerPass123!",
        )

        self.other_customer = User.objects.create_user(
            username="other_checkout_customer",
            password="CustomerPass123!",
        )

        self.seller = User.objects.create_user(
            username="checkout_seller",
            password="SellerPass123!",
        )

        SellerProfile.objects.create(
            user=self.seller,
            business_name="Checkout Test Store",
            status=SellerProfile.Status.APPROVED,
        )

        self.category = Category.objects.create(name="Checkout Food")

        self.product = Product.objects.create(
            owner=self.seller,
            category=self.category,
            name="Test Rice",
            description="Rice for checkout tests",
            price=Decimal("2500.00"),
            stock_quantity=20,
            status=Product.Status.PUBLISHED,
        )

        self.checkout_url = "/api/checkout/"
        self.orders_url = "/api/customer/orders/"

        self.client.force_authenticate(user=self.customer)

    def test_customer_can_checkout_and_stock_is_deducted(self):
        response = self.client.post(
            self.checkout_url,
            {
                "items": [
                    {
                        "product_id": self.product.id,
                        "quantity": 3,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        order = CustomerOrder.objects.get(
            order_number=response.data["order_number"]
        )

        self.assertEqual(order.customer, self.customer)
        self.assertEqual(order.total_amount, Decimal("7500.00"))
        self.assertEqual(order.items.count(), 1)

        item = order.items.get()
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.seller, self.seller)
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.unit_price, Decimal("2500.00"))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 17)

        movement = InventoryMovement.objects.get(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_OUT,
        )
        self.assertEqual(movement.quantity, 3)
        self.assertEqual(movement.created_by, self.customer)

    def test_client_cannot_set_order_price_or_total(self):
        response = self.client.post(
            self.checkout_url,
            {
                "total_amount": "1.00",
                "status": "DELIVERED",
                "items": [
                    {
                        "product_id": self.product.id,
                        "quantity": 2,
                        "unit_price": "0.01",
                        "seller": self.other_customer.id,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        order = CustomerOrder.objects.get(
            order_number=response.data["order_number"]
        )
        self.assertEqual(order.total_amount, Decimal("5000.00"))

        item = order.items.get()
        self.assertEqual(item.unit_price, Decimal("2500.00"))
        self.assertEqual(item.seller, self.seller)
        self.assertEqual(order.status, CustomerOrder.Status.PENDING)

    def test_checkout_rejects_insufficient_stock_without_changes(self):
        response = self.client.post(
            self.checkout_url,
            {
                "items": [
                    {
                        "product_id": self.product.id,
                        "quantity": 999,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)
        self.assertEqual(CustomerOrder.objects.count(), 0)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_checkout_rejects_unpublished_product(self):
        self.product.status = Product.Status.DRAFT
        self.product.save(update_fields=["status"])

        response = self.client.post(
            self.checkout_url,
            {
                "items": [
                    {
                        "product_id": self.product.id,
                        "quantity": 1,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)
        self.assertEqual(CustomerOrder.objects.count(), 0)

    def test_customer_can_list_only_their_own_orders(self):
        own_order = CustomerOrder.objects.create(
            order_number="CO-OWN-TEST-001",
            customer=self.customer,
            total_amount=Decimal("2500.00"),
        )

        CustomerOrderItem.objects.create(
            order=own_order,
            product=self.product,
            seller=self.seller,
            quantity=1,
            unit_price=Decimal("2500.00"),
        )

        CustomerOrder.objects.create(
            order_number="CO-OTHER-TEST-001",
            customer=self.other_customer,
            total_amount=Decimal("5000.00"),
        )

        response = self.client.get(self.orders_url)

        self.assertEqual(response.status_code, 200)

        order_numbers = [
            item["order_number"]
            for item in response.data["results"]
        ]
        self.assertEqual(order_numbers, ["CO-OWN-TEST-001"])

    def test_customer_cannot_retrieve_another_customers_order(self):
        other_order = CustomerOrder.objects.create(
            order_number="CO-PRIVATE-TEST-001",
            customer=self.other_customer,
            total_amount=Decimal("2500.00"),
        )

        response = self.client.get(
            f"{self.orders_url}{other_order.id}/"
        )

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_customer_cannot_checkout(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            self.checkout_url,
            {
                "items": [
                    {
                        "product_id": self.product.id,
                        "quantity": 1,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(CustomerOrder.objects.count(), 0)

    def test_customer_can_cancel_own_order_and_restore_stock(self):
        checkout_response = self.client.post(
            self.checkout_url,
            {
                "items": [
                    {
                        "product_id": self.product.id,
                        "quantity": 3,
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(checkout_response.status_code, 201)

        order = CustomerOrder.objects.get(
            order_number=checkout_response.data["order_number"]
        )
        cancel_url = f"/api/customer/orders/{order.id}/cancel/"

        response = self.client.post(cancel_url)

        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        self.product.refresh_from_db()
        item = order.items.get()

        self.assertEqual(order.status, CustomerOrder.Status.CANCELLED)
        self.assertEqual(
            item.fulfillment_status,
            CustomerOrderItem.FulfillmentStatus.CANCELLED,
        )
        self.assertEqual(self.product.stock_quantity, 20)

        movement = InventoryMovement.objects.get(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
        )
        self.assertEqual(movement.quantity, 3)
        self.assertEqual(movement.created_by, self.customer)

    def test_customer_cannot_cancel_another_customers_order(self):
        order = CustomerOrder.objects.create(
            order_number="CO-CANCEL-OTHER-001",
            customer=self.other_customer,
            total_amount=Decimal("2500.00"),
        )
        CustomerOrderItem.objects.create(
            order=order,
            product=self.product,
            seller=self.seller,
            quantity=1,
            unit_price=Decimal("2500.00"),
        )

        response = self.client.post(
            f"/api/customer/orders/{order.id}/cancel/"
        )

        self.assertEqual(response.status_code, 404)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)
        self.assertEqual(
            InventoryMovement.objects.filter(
                product=self.product
            ).count(),
            0,
        )

    def test_customer_cannot_cancel_order_after_processing_starts(self):
        order = CustomerOrder.objects.create(
            order_number="CO-CANCEL-PROCESSING-001",
            customer=self.customer,
            total_amount=Decimal("2500.00"),
        )
        CustomerOrderItem.objects.create(
            order=order,
            product=self.product,
            seller=self.seller,
            quantity=2,
            unit_price=Decimal("2500.00"),
            fulfillment_status=(
                CustomerOrderItem.FulfillmentStatus.PROCESSING
            ),
        )

        response = self.client.post(
            f"/api/customer/orders/{order.id}/cancel/"
        )

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)
        self.assertEqual(order.status, CustomerOrder.Status.PENDING)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_customer_cannot_cancel_same_order_twice(self):
        checkout_response = self.client.post(
            self.checkout_url,
            {
                "items": [
                    {
                        "product_id": self.product.id,
                        "quantity": 2,
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(checkout_response.status_code, 201)

        order = CustomerOrder.objects.get(
            order_number=checkout_response.data["order_number"]
        )
        cancel_url = f"/api/customer/orders/{order.id}/cancel/"

        first_response = self.client.post(cancel_url)
        second_response = self.client.post(cancel_url)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)
        self.assertEqual(
            InventoryMovement.objects.filter(
                product=self.product,
                movement_type=InventoryMovement.MovementType.STOCK_IN,
            ).count(),
            1,
        )

    def test_unauthenticated_customer_cannot_cancel_order(self):
        order = CustomerOrder.objects.create(
            order_number="CO-CANCEL-ANON-001",
            customer=self.customer,
            total_amount=Decimal("2500.00"),
        )
        CustomerOrderItem.objects.create(
            order=order,
            product=self.product,
            seller=self.seller,
            quantity=1,
            unit_price=Decimal("2500.00"),
        )

        self.client.force_authenticate(user=None)

        response = self.client.post(
            f"/api/customer/orders/{order.id}/cancel/"
        )

        self.assertEqual(response.status_code, 401)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)



class SellerOrderManagementTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="order_customer",
            password="CustomerPass123!",
        )
        self.seller = User.objects.create_user(
            username="order_seller",
            password="SellerPass123!",
        )
        self.other_seller = User.objects.create_user(
            username="other_order_seller",
            password="SellerPass123!",
        )
        self.unapproved_seller = User.objects.create_user(
            username="pending_order_seller",
            password="SellerPass123!",
        )

        SellerProfile.objects.create(
            user=self.seller,
            business_name="Approved Store",
            status=SellerProfile.Status.APPROVED,
        )
        SellerProfile.objects.create(
            user=self.other_seller,
            business_name="Other Approved Store",
            status=SellerProfile.Status.APPROVED,
        )
        SellerProfile.objects.create(
            user=self.unapproved_seller,
            business_name="Pending Store",
            status=SellerProfile.Status.PENDING,
        )

        category = Category.objects.create(name="Order Management Food")

        self.product = Product.objects.create(
            owner=self.seller,
            category=category,
            name="Seller Rice",
            description="Rice for seller order tests",
            price=Decimal("1000.00"),
            stock_quantity=10,
            status=Product.Status.PUBLISHED,
        )
        self.other_product = Product.objects.create(
            owner=self.other_seller,
            category=category,
            name="Other Seller Rice",
            description="Rice owned by another seller",
            price=Decimal("1500.00"),
            stock_quantity=8,
            status=Product.Status.PUBLISHED,
        )

        self.order = CustomerOrder.objects.create(
            order_number="CO-SELLER-TEST-001",
            customer=self.customer,
            total_amount=Decimal("2000.00"),
        )
        self.item = CustomerOrderItem.objects.create(
            order=self.order,
            product=self.product,
            seller=self.seller,
            quantity=2,
            unit_price=Decimal("1000.00"),
        )
        self.other_order = CustomerOrder.objects.create(
            order_number="CO-SELLER-TEST-002",
            customer=self.customer,
            total_amount=Decimal("1500.00"),
        )
        self.other_item = CustomerOrderItem.objects.create(
            order=self.other_order,
            product=self.other_product,
            seller=self.other_seller,
            quantity=1,
            unit_price=Decimal("1500.00"),
        )

        self.list_url = "/api/seller/orders/"
        self.status_url = (
            f"/api/seller/orders/{self.item.id}/status/"
        )

        self.client.force_authenticate(user=self.seller)

    def test_seller_list_contains_only_own_order_items(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        item_ids = [row["id"] for row in results]

        self.assertIn(self.item.id, item_ids)
        self.assertNotIn(self.other_item.id, item_ids)

    def test_seller_cannot_retrieve_another_sellers_item(self):
        response = self.client.get(
            f"/api/seller/orders/{self.other_item.id}/"
        )

        self.assertEqual(response.status_code, 404)

    def test_seller_cannot_update_another_sellers_item(self):
        response = self.client.patch(
            f"/api/seller/orders/{self.other_item.id}/status/",
            {"fulfillment_status": "CONFIRMED"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.other_item.refresh_from_db()
        self.assertEqual(
            self.other_item.fulfillment_status,
            CustomerOrderItem.FulfillmentStatus.PENDING,
        )

    def test_seller_can_confirm_order_item(self):
        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CONFIRMED"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(
            self.item.fulfillment_status,
            CustomerOrderItem.FulfillmentStatus.CONFIRMED,
        )

    def test_invalid_status_transition_is_rejected(self):
        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "DELIVERED"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(
            self.item.fulfillment_status,
            CustomerOrderItem.FulfillmentStatus.PENDING,
        )

    def test_cancellation_restores_stock_and_records_movement(self):
        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CANCELLED"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.product.refresh_from_db()
        self.item.refresh_from_db()

        self.assertEqual(self.product.stock_quantity, 12)
        self.assertEqual(
            self.item.fulfillment_status,
            CustomerOrderItem.FulfillmentStatus.CANCELLED,
        )

        movement = InventoryMovement.objects.get(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
        )
        self.assertEqual(movement.quantity, 2)
        self.assertEqual(movement.created_by, self.seller)

    def test_cancelled_item_cannot_restore_stock_twice(self):
        first_response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CANCELLED"},
            format="json",
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CANCELLED"},
            format="json",
        )
        self.assertEqual(second_response.status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 12)

        movements = InventoryMovement.objects.filter(
            product=self.product,
            movement_type=InventoryMovement.MovementType.STOCK_IN,
        )
        self.assertEqual(movements.count(), 1)

    def test_unapproved_seller_cannot_update_order_status(self):
        self.client.force_authenticate(user=self.unapproved_seller)

        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CONFIRMED"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_cannot_update_order_status(self):
        self.client.force_authenticate(user=None)

        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CONFIRMED"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    def test_order_status_updates_when_all_items_are_delivered(self):
        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CONFIRMED"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "PROCESSING"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "SHIPPED"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "DELIVERED"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(
            self.order.status,
            CustomerOrder.Status.DELIVERED,
        )

    def test_order_remains_pending_while_another_item_is_pending(self):
        second_item = CustomerOrderItem.objects.create(
            order=self.order,
            product=self.other_product,
            seller=self.other_seller,
            quantity=1,
            unit_price=Decimal("1500.00"),
        )

        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CONFIRMED"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(
            self.order.status,
            CustomerOrder.Status.PENDING,
        )

    def test_cancelling_one_item_does_not_cancel_order_with_active_items(self):
        second_item = CustomerOrderItem.objects.create(
            order=self.order,
            product=self.other_product,
            seller=self.other_seller,
            quantity=1,
            unit_price=Decimal("1500.00"),
        )

        response = self.client.patch(
            self.status_url,
            {"fulfillment_status": "CANCELLED"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        second_item.refresh_from_db()

        self.assertEqual(
            self.order.status,
            CustomerOrder.Status.PENDING,
        )
        self.assertEqual(
            second_item.fulfillment_status,
            CustomerOrderItem.FulfillmentStatus.PENDING,
        )

class CustomerCartAPITests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cart_customer",
            password="CustomerPass123!",
        )

        self.other_customer = User.objects.create_user(
            username="other_cart_customer",
            password="CustomerPass123!",
        )

        self.seller = User.objects.create_user(
            username="cart_seller",
            password="SellerPass123!",
        )

        SellerProfile.objects.create(
            user=self.seller,
            business_name="Cart Test Store",
            status=SellerProfile.Status.APPROVED,
        )

        self.category = Category.objects.create(
            name="Cart Test Category",
        )

        self.product = Product.objects.create(
            owner=self.seller,
            category=self.category,
            name="Cart Test Rice",
            description="Rice for cart tests",
            price=Decimal("2500.00"),
            stock_quantity=20,
            status=Product.Status.PUBLISHED,
        )

        self.cart_url = "/api/cart/"
        self.cart_items_url = "/api/cart/items/"
        self.cart_checkout_url = "/api/cart/checkout/"
        self.direct_checkout_url = "/api/checkout/"

        self.client.force_authenticate(user=self.customer)

    def add_product(self, product=None, quantity=1):
        product = product or self.product

        return self.client.post(
            self.cart_items_url,
            {
                "product_id": product.id,
                "quantity": quantity,
            },
            format="json",
        )

    def test_customer_can_view_empty_cart(self):
        response = self.client.get(self.cart_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_items"], 0)
        self.assertEqual(
            Decimal(str(response.data["total_amount"])),
            Decimal("0.00"),
        )
        self.assertEqual(response.data["items"], [])

    def test_customer_can_add_product_to_cart(self):
        response = self.add_product(quantity=2)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["product"], self.product.id)
        self.assertEqual(response.data["quantity"], 2)

        cart = Cart.objects.get(customer=self.customer)

        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.get().quantity, 2)

    def test_adding_same_product_increments_quantity(self):
        first_response = self.add_product(quantity=2)
        second_response = self.add_product(quantity=3)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)

        cart = Cart.objects.get(customer=self.customer)

        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.get().quantity, 5)

    def test_customer_can_update_cart_item_quantity(self):
        self.add_product(quantity=2)

        cart_item = CartItem.objects.get(
            cart__customer=self.customer,
            product=self.product,
        )

        response = self.client.patch(
            f"{self.cart_items_url}{cart_item.id}/",
            {"quantity": 4},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        cart_item.refresh_from_db()
        self.assertEqual(cart_item.quantity, 4)

    def test_customer_can_remove_cart_item(self):
        self.add_product(quantity=2)

        cart_item = CartItem.objects.get(
            cart__customer=self.customer,
            product=self.product,
        )

        response = self.client.delete(
            f"{self.cart_items_url}{cart_item.id}/",
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            CartItem.objects.filter(pk=cart_item.pk).exists()
        )

    def test_cannot_add_quantity_above_available_stock(self):
        response = self.add_product(quantity=21)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            CartItem.objects.filter(
                cart__customer=self.customer,
                product=self.product,
            ).exists()
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

    def test_cannot_increase_cart_quantity_above_available_stock(self):
        self.add_product(quantity=15)

        cart_item = CartItem.objects.get(
            cart__customer=self.customer,
            product=self.product,
        )

        response = self.client.patch(
            f"{self.cart_items_url}{cart_item.id}/",
            {"quantity": 21},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        cart_item.refresh_from_db()
        self.assertEqual(cart_item.quantity, 15)


    def test_customer_cannot_update_another_customers_cart_item(self):
        # Arrange: create a cart item belonging to another customer.
        other_cart, _ = Cart.objects.get_or_create(
            customer=self.other_customer,
        )

        other_item = CartItem.objects.create(
            cart=other_cart,
            product=self.product,
            quantity=1,
        )

        # Authenticate as the first customer, not the item's owner.
        self.client.force_authenticate(user=self.customer)

        # Act: attempt to modify another customer's cart item.
        response = self.client.patch(
            f"{self.cart_items_url}{other_item.id}/",
            {"quantity": 5},
            format="json",
        )

        # Assert: access must be denied without changing the item.
        self.assertEqual(response.status_code, 404)

        other_item.refresh_from_db()
        self.assertEqual(other_item.quantity, 1)


    def test_customer_cannot_delete_another_customers_cart_item(self):
        other_cart, _ = Cart.objects.get_or_create(
            customer=self.other_customer,
        )

        other_item = CartItem.objects.create(
            cart=other_cart,
            product=self.product,
            quantity=1,
        )

        response = self.client.delete(
            f"{self.cart_items_url}{other_item.id}/",
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            CartItem.objects.filter(pk=other_item.pk).exists()
        )

    def test_customer_can_checkout_cart(self):
        self.add_product(quantity=3)

        response = self.client.post(
            self.cart_checkout_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        order = CustomerOrder.objects.get(
            order_number=response.data["order_number"],
        )

        self.assertEqual(order.customer, self.customer)
        self.assertEqual(order.total_amount, Decimal("7500.00"))
        self.assertEqual(order.items.count(), 1)

        order_item = order.items.get()

        self.assertEqual(order_item.product, self.product)
        self.assertEqual(order_item.seller, self.seller)
        self.assertEqual(order_item.quantity, 3)
        self.assertEqual(
            order_item.unit_price,
            Decimal("2500.00"),
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 17)

        cart = Cart.objects.get(customer=self.customer)
        self.assertEqual(cart.items.count(), 0)

        self.assertTrue(
            InventoryMovement.objects.filter(
                product=self.product,
                movement_type=InventoryMovement.MovementType.STOCK_OUT,
                quantity=3,
                created_by=self.customer,
            ).exists()
        )

    def test_cannot_checkout_empty_cart(self):
        response = self.client.post(
            self.cart_checkout_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(CustomerOrder.objects.count(), 0)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

    def test_failed_checkout_preserves_cart_and_stock(self):
        self.add_product(quantity=5)

        self.product.stock_quantity = 2
        self.product.save(update_fields=["stock_quantity"])

        response = self.client.post(
            self.cart_checkout_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        cart = Cart.objects.get(customer=self.customer)

        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.get().quantity, 5)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 2)

        self.assertEqual(CustomerOrder.objects.count(), 0)

    def test_direct_checkout_still_works(self):
        response = self.client.post(
            self.direct_checkout_url,
            {
                "items": [
                    {
                        "product_id": self.product.id,
                        "quantity": 2,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 18)

    def test_unauthenticated_user_cannot_access_cart(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.cart_url)

        self.assertEqual(response.status_code, 401)

    def test_unauthenticated_user_cannot_add_cart_item(self):
        self.client.force_authenticate(user=None)

        response = self.add_product(quantity=1)

        self.assertEqual(response.status_code, 401)
