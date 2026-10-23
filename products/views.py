
from django_filters import rest_framework
from rest_framework import generics, permissions
from rest_framework.decorators import (
    api_view,
    permission_classes,
)
from rest_framework.response import Response

from .models import Product
from .serializers import ProductSerializer ,UserRegistrationSerializer
from .permissions import IsAdminOrReadOnly
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import InventoryMovement
from .serializers import InventoryMovementSerializer
from django.db.models import Count, DecimalField, F, Q, Sum
from rest_framework.permissions import IsAdminUser
from rest_framework.exceptions import ValidationError
from rest_framework import serializers
from .models import Category
from .serializers import CategorySerializer, SupplierSerializer
from .models import Supplier
from .models import PurchaseOrder, PurchaseOrderItem
from .serializers import PurchaseOrderSerializer
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from django.db import transaction
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError as DRFValidationError
from decimal import Decimal




@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def health_check(request):
    return Response({
        "status": "ok",
        "message": "Shop API is running",
    })


class ProductListCreateView(generics.ListCreateAPIView):
    queryset = Product.objects.all().order_by("id")
    serializer_class = ProductSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_fields = ["category", "price"]
    search_fields = ["name", "description", "category__name"]
    ordering_fields = ["name", "price", "created_at", "stock_quantity"]
    ordering = ["id"]
    
class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAdminOrReadOnly]


class UserRegistrationView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]
    
    

class InventoryMovementCreateView(generics.CreateAPIView):
    queryset = InventoryMovement.objects.all()
    serializer_class = InventoryMovementSerializer
    permission_classes = [permissions.IsAdminUser]




class InventoryMovementListView(generics.ListAPIView):
    serializer_class = InventoryMovementSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        queryset = InventoryMovement.objects.select_related(
            "product",
            "created_by",
        ).all()

        product_id = self.request.query_params.get("product_id")
        movement_type = self.request.query_params.get("movement_type")

        if product_id is not None:
            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                raise serializers.ValidationError({
                    "product_id": "Must be a valid integer."
                })

            if product_id < 1:
                raise serializers.ValidationError({
                    "product_id": "Must be greater than zero."
                })

            queryset = queryset.filter(product_id=product_id)

        if movement_type is not None:
            movement_type = movement_type.upper()

            allowed_types = [
                InventoryMovement.MovementType.STOCK_IN,
                InventoryMovement.MovementType.STOCK_OUT,
            ]

            if movement_type not in allowed_types:
                raise serializers.ValidationError({
                    "movement_type": "Must be IN or OUT."
                })

            queryset = queryset.filter(
                movement_type=movement_type
            )

        return queryset




@api_view(["GET"])
@permission_classes([IsAdminUser])
def inventory_summary(request):
    products = list(
        Product.objects.all().order_by("id")
    )

    movement_totals = (
        InventoryMovement.objects
        .values("product_id")
        .annotate(
            stock_in=Sum(
                "quantity",
                filter=Q(
                    movement_type=InventoryMovement.MovementType.STOCK_IN
                ),
            ),
            stock_out=Sum(
                "quantity",
                filter=Q(
                    movement_type=InventoryMovement.MovementType.STOCK_OUT
                ),
            ),
        )
    )

    totals_by_product = {
        item["product_id"]: item
        for item in movement_totals
    }

    results = []

    for product in products:
        totals = totals_by_product.get(product.id, {})

        results.append({
            "product_id": product.id,
            "product_name": product.name,
            "stock_in_total": totals.get("stock_in") or 0,
            "stock_out_total": totals.get("stock_out") or 0,
            "current_stock": product.stock_quantity,
        })

    return Response({
        "total_products": len(results),
        "inventory": results,
    })


@api_view(["GET"])
@permission_classes([IsAdminUser])
def low_stock_products(request):
    raw_threshold = request.query_params.get("threshold", "5")

    try:
        threshold = int(raw_threshold)
    except (TypeError, ValueError):
        raise ValidationError({
            "threshold": "Threshold must be a whole number."
        })

    if threshold < 0:
        raise ValidationError({
            "threshold": "Threshold cannot be negative."
        })

    products = Product.objects.filter(
        stock_quantity__lt=threshold
    ).order_by("stock_quantity", "name")

    results = [
        {
            "product_id": product.id,
            "product_name": product.name,
            "current_stock": product.stock_quantity,
            "threshold": threshold,
        }
        for product in products
    ]

    return Response({
        "threshold": threshold,
        "count": len(results),
        "low_stock_products": results,
    })



class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]



class SupplierListCreateView(generics.ListCreateAPIView):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAdminOrReadOnly]


class SupplierDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAdminOrReadOnly]



class PurchaseOrderSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        # Calculate all status counts in a single database aggregation.
        summary = PurchaseOrder.objects.aggregate(
            total_orders=Count("id"),
            draft_orders=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.DRAFT),
            ),
            ordered_orders=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.ORDERED),
            ),
            received_orders=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.RECEIVED),
            ),
            cancelled_orders=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.CANCELLED),
            ),
        )

        # Calculate the value in the database while preserving decimal precision.
        total_value = PurchaseOrderItem.objects.aggregate(
            value=Sum(
                F("quantity") * F("unit_cost"),
                output_field=DecimalField(
                    max_digits=20,
                    decimal_places=2,
                ),
            )
        )["value"]

        if total_value is None:
            total_value = Decimal("0.00")

        summary["total_value"] = str(total_value)

        return Response(summary)
class PurchaseOrderListCreateView(generics.ListCreateAPIView):
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAdminUser]
    ordering_fields = [
        "created_at",
        "updated_at",
        "order_number",
        "status",
    ]
    ordering = ["-created_at"]
    filter_backends = [OrderingFilter]

    def get_queryset(self):
        queryset = PurchaseOrder.objects.select_related(
            "supplier",
            "created_by",
        ).prefetch_related(
            "items__product"
        )

        params = self.request.query_params

        # Filter by purchase order status.
        order_status = params.get("status")
        if order_status:
            valid_statuses = PurchaseOrder.Status.values

            if order_status not in valid_statuses:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({
                    "status": (
                        "Invalid purchase order status. "
                        f"Choose from: {', '.join(valid_statuses)}."
                    )
                })

            queryset = queryset.filter(status=order_status)

        
        # Filter by supplier ID.
        supplier_id = params.get("supplier")
        if supplier_id:
            if not supplier_id.isdigit():
                raise DRFValidationError({
                    "supplier": "Supplier must be a valid numeric ID."
                })

            supplier_id = int(supplier_id)

            if not Supplier.objects.filter(id=supplier_id).exists():
                raise DRFValidationError({
                    "supplier": "Supplier with this ID does not exist."
                })

            queryset = queryset.filter(supplier_id=supplier_id)

        # Filter by order number.
        order_number = params.get("order_number")
        if order_number:
            queryset = queryset.filter(
                order_number__icontains=order_number
            )
        
        
        # Filter by creation date.
        created_after = params.get("created_after")
        created_before = params.get("created_before")

        parsed_after = None
        parsed_before = None

        if created_after:
            try:
                parsed_after = parse_date(created_after)
            except ValueError:
                parsed_after = None

            if parsed_after is None:
                raise DRFValidationError({
                    "created_after": (
                        "Invalid date. Use YYYY-MM-DD format."
                    )
                })

        if created_before:
            try:
                parsed_before = parse_date(created_before)
            except ValueError:
                parsed_before = None

            if parsed_before is None:
                raise DRFValidationError({
                    "created_before": (
                        "Invalid date. Use YYYY-MM-DD format."
                    )
                })

        # Validate the date range before filtering.
        if (
            parsed_after is not None
            and parsed_before is not None
            and parsed_after > parsed_before
        ):
            raise DRFValidationError({
                "date_range": (
                    "'created_after' must be on or before "
                    "'created_before'."
                )
            })

        # Apply validated date filters.
        if parsed_after is not None:
            queryset = queryset.filter(
                created_at__date__gte=parsed_after
            )

        if parsed_before is not None:
            queryset = queryset.filter(
                created_at__date__lte=parsed_before
            )

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PurchaseOrderDetailView(generics.RetrieveAPIView):
    queryset = PurchaseOrder.objects.select_related(
        "supplier",
        "created_by",
    ).prefetch_related(
        "items__product"
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAdminUser]
    
    
class PurchaseOrderMarkOrderedView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @transaction.atomic
    def post(self, request, pk):
        try:
            purchase_order = (
                PurchaseOrder.objects.select_for_update().get(pk=pk)
            )
        except PurchaseOrder.DoesNotExist:
            return Response(
                {"detail": "Purchase order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase_order.status != PurchaseOrder.Status.DRAFT:
            return Response(
                {"detail": "Only draft orders can be marked as ordered."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not purchase_order.items.exists():
            return Response(
                {"detail": "Cannot order a purchase order with no items."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not purchase_order.supplier.is_active:
            return Response(
                {"detail": "Cannot order from an inactive supplier."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        purchase_order.status = PurchaseOrder.Status.ORDERED
        purchase_order.save(update_fields=["status", "updated_at"])

        return Response({
            "id": purchase_order.id,
            "order_number": purchase_order.order_number,
            "status": purchase_order.status,
            "message": "Purchase order marked as ordered.",
        })


class PurchaseOrderReceiveView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @transaction.atomic
    def post(self, request, pk):
        try:
            purchase_order = (
                PurchaseOrder.objects.select_for_update().get(pk=pk)
            )
        except PurchaseOrder.DoesNotExist:
            return Response(
                {"detail": "Purchase order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase_order.status != PurchaseOrder.Status.ORDERED:
            return Response(
                {
                    "detail": (
                        "Only ordered purchase orders can be received. "
                        f"Current status: {purchase_order.status}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = list(
            purchase_order.items.all().order_by("product_id")
        )

        if not items:
            return Response(
                {"detail": "Cannot receive an order with no items."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for item in items:
            product = Product.objects.select_for_update().get(
                pk=item.product_id
            )

            product.stock_quantity += item.quantity
            product.save(
                update_fields=["stock_quantity", "updated_at"]
            )

            InventoryMovement.objects.create(
                product=product,
                movement_type=InventoryMovement.MovementType.STOCK_IN,
                quantity=item.quantity,
                note=f"Received against {purchase_order.order_number}",
                created_by=request.user,
            )

        purchase_order.status = PurchaseOrder.Status.RECEIVED
        purchase_order.received_at = timezone.now()
        purchase_order.save(
            update_fields=["status", "received_at", "updated_at"]
        )

        return Response({
            "id": purchase_order.id,
            "order_number": purchase_order.order_number,
            "status": purchase_order.status,
            "received_at": purchase_order.received_at,
            "message": "Purchase order received successfully.",
        })


class PurchaseOrderCancelView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @transaction.atomic
    def post(self, request, pk):
        try:
            purchase_order = (
                PurchaseOrder.objects
                .select_for_update()
                .get(pk=pk)
            )
        except PurchaseOrder.DoesNotExist:
            return Response(
                {"detail": "Purchase order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase_order.status not in [
            PurchaseOrder.Status.DRAFT,
            PurchaseOrder.Status.ORDERED,
        ]:
            return Response(
                {
                    "detail": (
                        "Only draft or ordered purchase orders "
                        "can be cancelled. "
                        f"Current status: {purchase_order.status}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(
            update_fields=["status", "updated_at"]
        )

        return Response(
            {
                "id": purchase_order.id,
                "order_number": purchase_order.order_number,
                "status": purchase_order.status,
                "message": "Purchase order cancelled successfully.",
            },
            status=status.HTTP_200_OK,
        )