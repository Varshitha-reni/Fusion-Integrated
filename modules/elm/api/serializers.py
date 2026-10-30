from rest_framework import serializers

from modules.elm.models import LeaveApplication, LeaveBalanceTransaction


class LeaveApplicationWriteSerializer(serializers.Serializer):
    category = serializers.ChoiceField(
        choices=LeaveApplication.CATEGORY
    )
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    purpose = serializers.CharField()
    half_day_session = serializers.ChoiceField(
        choices=LeaveApplication.HALF_DAY,
        required=False,
        default="",
    )
    station_leave_required = serializers.BooleanField(
        required=False,
        default=False,
    )
    station_leave_details = serializers.DictField(
        required=False,
        default=dict,
    )

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError(
                {"end_date": "End date cannot be before start date."}
            )

        if attrs["half_day_session"] and (
            attrs["category"] != "CL"
            or attrs["start_date"] != attrs["end_date"]
        ):
            raise serializers.ValidationError(
                "Half-day applications are allowed only for one-day CL."
            )

        return attrs


class LeaveApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveApplication
        fields = (
            "id",
            "category",
            "start_date",
            "end_date",
            "half_day_session",
            "chargeable_days",
            "purpose",
            "station_leave_required",
            "station_leave_details",
            "status",
            "submitted_at",
            "created_at",
        )
        read_only_fields = fields


class SubmissionPreflightSerializer(serializers.Serializer):
    application_id = serializers.IntegerField()
    chargeable_days = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
    )
    available_days = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
    )
    remaining_days = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
    )
    period_year = serializers.IntegerField()

class LeaveBalanceSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    category = serializers.CharField(read_only=True)
    period_year = serializers.IntegerField(read_only=True)
    entitlement_days = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        read_only=True,
    )
    opening_balance = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        read_only=True,
    )
    available_days = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        read_only=True,
    )


class LeaveBalanceTransactionSerializer(serializers.ModelSerializer):
    category = serializers.CharField(
        source="balance.category",
        read_only=True,
    )
    period_year = serializers.IntegerField(
        source="balance.period_year",
        read_only=True,
    )

    class Meta:
        model = LeaveBalanceTransaction
        fields = (
            "id",
            "category",
            "period_year",
            "transaction_type",
            "delta_days",
            "balance_after",
            "effective_date",
            "description",
            "created_at",
        )
        read_only_fields = fields
