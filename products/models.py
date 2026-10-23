

from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name



class InventoryMovement(models.Model):
    class MovementType(models.TextChoices):
        STOCK_IN = "IN", "Stock In"
        STOCK_OUT = "OUT", "Stock Out"

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="inventory_movements",
    )
    movement_type = models.CharField(
        max_length=3,
        choices=MovementType.choices,
    )
    quantity = models.PositiveIntegerField()
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="inventory_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.product.name} - "
            f"{self.get_movement_type_display()} "
            f"({self.quantity})"
        )



class Supplier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    contact_person = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ORDERED = "ORDERED", "Ordered"
        RECEIVED = "RECEIVED", "Received"
        CANCELLED = "CANCELLED", "Cancelled"

    order_number = models.CharField(
        max_length=30,
        unique=True,
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_number


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="purchase_order_items",
    )

    quantity = models.PositiveIntegerField()

    unit_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["purchase_order", "product"],
                name="unique_product_per_purchase_order",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="purchase_order_item_quantity_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost__gt=0),
                name="purchase_order_item_unit_cost_gt_zero",
            ),
        ]

    def __str__(self):
        return (
            f"{self.purchase_order.order_number} - "
            f"{self.product.name} x {self.quantity}"
        )