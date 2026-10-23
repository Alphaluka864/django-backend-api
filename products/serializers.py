
from rest_framework import serializers
from .models import Product, Category, InventoryMovement,Supplier
from django.contrib.auth.models import User

from django.db import transaction
from rest_framework import serializers
from .models import PurchaseOrder, PurchaseOrderItem


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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]




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

        return attrs

    def create(self, validated_data):
        validated_data.pop("password2")

        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
        )

        return user



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

    def get_total_cost(self, obj):
        return sum(
            (item.quantity * item.unit_cost for item in obj.items.all()),
            start=0,
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