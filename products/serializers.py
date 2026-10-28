
from decimal import Decimal
import secrets

from django.contrib.auth.models import User
from django.db import transaction

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from .models import (
    Product,
    Category,
    InventoryMovement,
    Supplier,
    SellerProfile,
    PurchaseOrder,
    PurchaseOrderItem,
    ProductAuditLog,
    CustomerOrder,
    CustomerOrderItem,
)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "description", "created_at"]
        read_only_fields = ["id", "created_at"]


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source="category",
        write_only=True,
        required=False,
        allow_null=True,
    )

    def validate_status(self, value):
        if self.instance is not None:
            raise serializers.ValidationError(
                "Use the product workflow endpoints to change status."
            )
        return value

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price",
            "stock_quantity",
            "category",
            "category_id",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "stock_quantity",
            "status",
            "created_at",
            "updated_at",
        ]


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
    )
    password2 = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ["id", "username", "password", "password2"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({
                "password2": "Passwords do not match."
            })

        validate_password(
            attrs["password"],
            user=User(username=attrs.get("username", "")),
        )

        return attrs

    def create(self, validated_data):
        validated_data.pop("password2")

        return User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
        )


class SellerApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SellerProfile
        fields = [
            "id",
            "business_name",
            "description",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_at",
            "updated_at",
        ]

    def validate_business_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "Business name cannot be empty."
            )

        if SellerProfile.objects.filter(
            business_name__iexact=value
        ).exists():
            raise serializers.ValidationError(
                "A seller profile with this business name already exists."
            )

        return value

    def create(self, validated_data):
        request = self.context["request"]

        if SellerProfile.objects.filter(user=request.user).exists():
            raise serializers.ValidationError(
                "You already have a seller profile."
            )

        return SellerProfile.objects.create(
            user=request.user,
            **validated_data,
        )


class InventoryMovementSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(write_only=True)
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = InventoryMovement
        fields = [
            "id",
            "product_id",
            "product_name",
            "movement_type",
            "quantity",
            "note",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError(
                "Quantity must be greater than zero."
            )
        return value

    def validate_movement_type(self, value):
        allowed_types = [
            InventoryMovement.MovementType.STOCK_IN,
            InventoryMovement.MovementType.STOCK_OUT,
        ]

        if value not in allowed_types:
            raise serializers.ValidationError(
                "Movement type must be IN or OUT."
            )

        return value

    def validate_product_id(self, value):
        if not Product.objects.filter(pk=value).exists():
            raise serializers.ValidationError(
                "The specified product does not exist."
            )

        return value

    def create(self, validated_data):
        request = self.context["request"]
        product_id = validated_data.pop("product_id")

        with transaction.atomic():
            try:
                product = Product.objects.select_for_update().get(
                    pk=product_id
                )
            except Product.DoesNotExist:
                raise serializers.ValidationError({
                    "product_id": "This product does not exist."
                })

            quantity = validated_data["quantity"]

            if (
                validated_data["movement_type"]
                == InventoryMovement.MovementType.STOCK_IN
            ):
                product.stock_quantity += quantity
            else:
                if quantity > product.stock_quantity:
                    raise serializers.ValidationError({
                        "quantity": (
                            "Insufficient stock. "
                            f"Available: {product.stock_quantity}."
                        )
                    })

                product.stock_quantity -= quantity

            product.save(
                update_fields=["stock_quantity", "updated_at"]
            )

            movement = InventoryMovement.objects.create(
                product=product,
                created_by=request.user,
                **validated_data,
            )

        return movement


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            "id",
            "name",
            "contact_person",
            "email",
            "phone",
            "address",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderItem
        fields = [
            "id",
            "product",
            "product_name",
            "quantity",
            "unit_cost",
            "line_total",
        ]
        read_only_fields = ["id", "product_name", "line_total"]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Quantity must be greater than zero."
            )
        return value

    def validate_unit_cost(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Unit cost must be greater than zero."
            )
        return value

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_line_total(self, obj):
        return obj.quantity * obj.unit_cost


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True)
    supplier_name = serializers.CharField(
        source="supplier.name",
        read_only=True,
    )
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )
    total_cost = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "order_number",
            "supplier",
            "supplier_name",
            "status",
            "notes",
            "items",
            "total_cost",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "received_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "received_at",
            "total_cost",
        ]

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError(
                "A purchase order must contain at least one item."
            )

        product_ids = [item["product"].id for item in value]

        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "A product can appear only once in a purchase order."
            )

        return value

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_cost(self, obj):
        return sum(
            (
                item.quantity * item.unit_cost
                for item in obj.items.all()
            ),
            start=Decimal("0.00"),
        )

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")

        purchase_order = PurchaseOrder.objects.create(
            **validated_data
        )

        for item_data in items_data:
            PurchaseOrderItem.objects.create(
                purchase_order=purchase_order,
                **item_data,
            )

        return purchase_order


class ProductAuditLogSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    actor_username = serializers.CharField(
        source="actor.username",
        read_only=True,
    )

    class Meta:
        model = ProductAuditLog
        fields = [
            "id",
            "product",
            "product_name",
            "actor",
            "actor_username",
            "action",
            "previous_status",
            "new_status",
            "created_at",
        ]
        read_only_fields = fields


class SellerProfileAdminSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        source="user.username",
        read_only=True,
    )

    class Meta:
        model = SellerProfile
        fields = [
            "id",
            "username",
            "business_name",
            "description",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "username",
            "business_name",
            "description",
            "created_at",
            "updated_at",
        ]

    def validate_status(self, value):
        allowed_statuses = [
            SellerProfile.Status.APPROVED,
            SellerProfile.Status.REJECTED,
            SellerProfile.Status.SUSPENDED,
        ]

        if value not in allowed_statuses:
            raise serializers.ValidationError(
                "Invalid seller status."
            )

        return value


class CustomerOrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class CustomerOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = CustomerOrderItem
        fields = [
            "id",
            "product",
            "product_name",
            "seller",
            "quantity",
            "fulfillment_status",
            "unit_price",
            "line_total",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_line_total(self, obj):
        return obj.line_total


class SellerOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    order_number = serializers.CharField(
        source="order.order_number",
        read_only=True,
    )
    customer_username = serializers.CharField(
        source="order.customer.username",
        read_only=True,
    )
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = CustomerOrderItem
        fields = [
            "id",
            "order",
            "order_number",
            "customer_username",
            "product",
            "product_name",
            "quantity",
            "unit_price",
            "line_total",
            "fulfillment_status",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_line_total(self, obj):
        return obj.line_total


class CustomerOrderSerializer(serializers.ModelSerializer):
    items = CustomerOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = CustomerOrder
        fields = [
            "id",
            "order_number",
            "status",
            "total_amount",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CustomerCheckoutSerializer(serializers.Serializer):
    items = CustomerOrderItemInputSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError(
                "An order must contain at least one item."
            )

        product_ids = [item["product_id"] for item in items]

        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "Each product can appear only once in an order."
            )

        return items

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        requested_items = validated_data["items"]

        product_ids = sorted(
            item["product_id"] for item in requested_items
        )
        quantities = {
            item["product_id"]: item["quantity"]
            for item in requested_items
        }

        products = list(
            Product.objects
            .select_for_update(of=("self",))
            .filter(id__in=product_ids)
            .order_by("id")
            .select_related("owner")
        )

        products_by_id = {
            product.id: product for product in products
        }

        if len(products_by_id) != len(product_ids):
            raise serializers.ValidationError({
                "items": "One or more products do not exist."
            })

        for product_id in product_ids:
            product = products_by_id[product_id]
            quantity = quantities[product_id]

            if product.status != Product.Status.PUBLISHED:
                raise serializers.ValidationError({
                    "items": (
                        f"Product {product_id} is not available for sale."
                    )
                })

            if product.owner_id is None:
                raise serializers.ValidationError({
                    "items": (
                        f"Product {product_id} has no assigned seller."
                    )
                })

            seller_profile = SellerProfile.objects.filter(
                user_id=product.owner_id,
                status=SellerProfile.Status.APPROVED,
            ).exists()

            if not seller_profile:
                raise serializers.ValidationError({
                    "items": (
                        f"Product {product_id} does not have an "
                        "approved seller."
                    )
                })

            if product.price <= Decimal("0"):
                raise serializers.ValidationError({
                    "items": (
                        f"Product {product_id} has an invalid price."
                    )
                })

            if quantity > product.stock_quantity:
                raise serializers.ValidationError({
                    "items": (
                        f"Insufficient stock for {product.name}. "
                        f"Available: {product.stock_quantity}."
                    )
                })

        order = CustomerOrder.objects.create(
            order_number=f"CO-{secrets.token_hex(12).upper()}",
            customer=request.user,
            total_amount=Decimal("0.00"),
        )

        total = Decimal("0.00")

        for product_id in product_ids:
            product = products_by_id[product_id]
            quantity = quantities[product_id]
            unit_price = product.price

            CustomerOrderItem.objects.create(
                order=order,
                product=product,
                seller_id=product.owner_id,
                quantity=quantity,
                unit_price=unit_price,
            )

            product.stock_quantity -= quantity
            product.save(
                update_fields=["stock_quantity", "updated_at"]
            )

            InventoryMovement.objects.create(
                product=product,
                movement_type=InventoryMovement.MovementType.STOCK_OUT,
                quantity=quantity,
                note=f"Customer order {order.order_number}",
                created_by=request.user,
            )

            total += unit_price * quantity

        order.total_amount = total
        order.save(update_fields=["total_amount", "updated_at"])

        return order


class SellerOrderStatusUpdateSerializer(serializers.Serializer):
    fulfillment_status = serializers.ChoiceField(
        choices=CustomerOrderItem.FulfillmentStatus.choices,
    )
