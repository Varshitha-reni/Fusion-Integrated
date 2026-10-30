"""Employee Leave Management persistence models."""

from django.db import models
from django.db.models import Q

from core.db.mixins import TimeStampedModel, UserScopedModel


class LeaveApplication(TimeStampedModel, UserScopedModel):
    """A leave request submitted by an employee."""

    CATEGORY = [
        ("CL", "Casual Leave"),
        ("RH", "Restricted Holiday"),
        ("SCL", "Special Casual Leave"),
        ("EL", "Earned Leave"),
        ("COL", "Commuted Leave"),
        ("VL", "Vacation Leave"),
    ]

    STATUS = [
        ("draft", "Draft"),
        ("pending", "Pending"),
        ("applicant_action_required", "Applicant Action Required"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("withdrawn", "Withdrawn"),
        ("cancelled", "Cancelled"),
    ]

    HALF_DAY = [
        ("", "Full day"),
        ("first_half", "First half"),
        ("second_half", "Second half"),
    ]

    category = models.CharField(max_length=3, choices=CATEGORY)
    start_date = models.DateField()
    end_date = models.DateField()
    half_day_session = models.CharField(
        max_length=12, choices=HALF_DAY, blank=True, default=""
    )
    chargeable_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0
    )

    purpose = models.TextField()
    station_leave_required = models.BooleanField(default=False)
    station_leave_details = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=32, choices=STATUS, default="draft", db_index=True
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Preserve the facts used when the request was submitted.
    policy_snapshot = models.JSONField(default=dict, blank=True)
    applicant_context = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "elm_leave_application"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user_id", "status"],
                name="elm_app_user_status_idx",
            ),
            models.Index(
                fields=["start_date", "end_date"],
                name="elm_app_dates_idx",
            ),
            models.Index(
                fields=["category", "status"],
                name="elm_app_cat_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="elm_app_valid_date_range",
            ),
            models.CheckConstraint(
                condition=Q(chargeable_days__gte=0),
                name="elm_app_nonnegative_days",
            ),
            models.CheckConstraint(
                condition=(
                    Q(half_day_session="")
                    | (
                        Q(category="CL")
                        & Q(start_date=models.F("end_date"))
                        & Q(chargeable_days=0.5)
                    )
                ),
                name="elm_app_half_day_valid",
            ),
        ]

    def __str__(self):
        return (
            f"ELM-{self.pk}: user {self.user_id} "
            f"{self.category} ({self.start_date} to {self.end_date})"
        )


class LeaveBalance(TimeStampedModel, UserScopedModel):
    """Current balance snapshot for one employee/category/year."""

    CATEGORY = LeaveApplication.CATEGORY

    category = models.CharField(max_length=3, choices=CATEGORY)
    period_year = models.PositiveSmallIntegerField()

    entitlement_days = models.DecimalField(
        max_digits=8, decimal_places=2, default=0
    )
    opening_balance = models.DecimalField(
        max_digits=8, decimal_places=2, default=0
    )
    available_days = models.DecimalField(
        max_digits=8, decimal_places=2, default=0
    )

    class Meta:
        db_table = "elm_leave_balance"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "category", "period_year"],
                name="elm_balance_user_cat_year_uniq",
            ),
            models.CheckConstraint(
                condition=Q(entitlement_days__gte=0),
                name="elm_balance_entitlement_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(opening_balance__gte=0),
                name="elm_balance_opening_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(available_days__gte=0),
                name="elm_balance_available_nonneg",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user_id", "period_year"],
                name="elm_balance_user_year_idx",
            ),
        ]

    def __str__(self):
        return (
            f"user {self.user_id} {self.category} "
            f"{self.period_year}: {self.available_days}"
        )


class LeaveBalanceTransaction(TimeStampedModel):
    """Append-only record of a leave-account credit or debit."""

    TRANSACTION_TYPES = [
        ("opening_credit", "Opening credit"),
        ("annual_credit", "Annual entitlement credit"),
        ("leave_deduction", "Leave deduction"),
        ("cancellation_reversal", "Cancellation reversal"),
        ("extension_deduction", "Extension deduction"),
        ("resumption_adjustment", "Resumption adjustment"),
        ("year_end_lapse", "Year-end lapse"),
        ("vl_to_el_conversion", "VL to EL conversion"),
        ("offline_sync", "Offline leave synchronization"),
        ("admin_adjustment", "Administrative adjustment"),
    ]

    balance = models.ForeignKey(
        LeaveBalance,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    application = models.ForeignKey(
        LeaveApplication,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="balance_transactions",
    )

    transaction_type = models.CharField(
        max_length=32, choices=TRANSACTION_TYPES
    )
    # Positive values credit the account; negative values debit it.
    delta_days = models.DecimalField(max_digits=8, decimal_places=2)
    balance_after = models.DecimalField(max_digits=8, decimal_places=2)

    effective_date = models.DateField()
    reference_key = models.CharField(max_length=160, unique=True)
    description = models.CharField(max_length=300, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_by_user_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "elm_balance_transaction"
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(
                fields=["balance", "created_at"],
                name="elm_txn_balance_date_idx",
            ),
            models.Index(
                fields=["application", "transaction_type"],
                name="elm_txn_app_type_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(delta_days__gt=0) | Q(delta_days__lt=0),
                name="elm_txn_nonzero_delta",
            ),
            models.CheckConstraint(
                condition=Q(balance_after__gte=0),
                name="elm_txn_balance_nonneg",
            ),
        ]

    def __str__(self):
        return (
            f"{self.transaction_type}: {self.delta_days} "
            f"for balance {self.balance_id}"
        )


class LeaveTransition(models.Model):
    """Append-only audit record of an application status transition."""

    application = models.ForeignKey(
        LeaveApplication,
        on_delete=models.PROTECT,
        related_name="transitions",
    )

    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32)
    actor_user_id = models.IntegerField(null=True, blank=True)
    actor_role = models.CharField(max_length=80, blank=True)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "elm_leave_transition"
        ordering = ["at", "pk"]
        indexes = [
            models.Index(
                fields=["application", "at"],
                name="elm_transition_app_at_idx",
            ),
        ]

    def __str__(self):
        return (
            f"application {self.application_id}: "
            f"{self.from_status} -> {self.to_status}"
        )


# ---------------------------------------------------------------------------
# Workflow and substitute management
# ---------------------------------------------------------------------------

class LeaveWorkflowTask(TimeStampedModel):
    """An actionable task assigned during a leave-related workflow."""

    TASK_TYPES = [
        ("substitute_response", "Substitute response"),
        ("unit_head_review", "Unit Head review"),
        ("establishment_processing", "Establishment processing"),
        ("final_sanction", "Final sanction"),
        ("cancellation_review", "Cancellation review"),
        ("extension_review", "Extension review"),
        ("resumption_review", "Resumption review"),
    ]

    STATUS = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("escalated", "Escalated"),
    ]

    application = models.ForeignKey(
        LeaveApplication,
        on_delete=models.PROTECT,
        related_name="workflow_tasks",
    )
    task_type = models.CharField(max_length=32, choices=TASK_TYPES)
    status = models.CharField(
        max_length=12, choices=STATUS, default="pending", db_index=True
    )

    assigned_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    assigned_role = models.CharField(max_length=100, blank=True)

    assigned_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Identifies a cancellation, extension or resumption child case.
    related_case_type = models.CharField(max_length=20, blank=True)
    related_case_id = models.PositiveBigIntegerField(null=True, blank=True)

    dedupe_key = models.CharField(max_length=160, unique=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "elm_workflow_task"
        indexes = [
            models.Index(
                fields=["status", "due_at"],
                name="elm_task_status_due_idx",
            ),
            models.Index(
                fields=["assigned_user_id", "status"],
                name="elm_task_user_status_idx",
            ),
            models.Index(
                fields=["application", "status"],
                name="elm_task_app_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.task_type} for application {self.application_id}"


class SubstituteResponse(TimeStampedModel):
    """One substitute nomination and its response."""

    STATUS = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("replaced", "Replaced"),
        ("withdrawn", "Withdrawn"),
    ]

    application = models.ForeignKey(
        LeaveApplication,
        on_delete=models.PROTECT,
        related_name="substitute_responses",
    )

    substitute_user_id = models.IntegerField(db_index=True)
    nominated_by_user_id = models.IntegerField()
    status = models.CharField(
        max_length=12, choices=STATUS, default="pending", db_index=True
    )

    nominated_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    response_note = models.TextField(blank=True)

    replacement_for = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replacements",
    )

    class Meta:
        db_table = "elm_substitute_response"
        indexes = [
            models.Index(
                fields=["application", "status"],
                name="elm_sub_app_status_idx",
            ),
            models.Index(
                fields=["substitute_user_id", "status"],
                name="elm_sub_user_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(substitute_user_id=models.F("nominated_by_user_id")),
                name="elm_sub_not_nominator",
            ),
        ]

    def __str__(self):
        return (
            f"substitute {self.substitute_user_id} "
            f"for application {self.application_id}"
        )


# ---------------------------------------------------------------------------
# Cancellation, extension and resumption
# ---------------------------------------------------------------------------

class LeaveCancellation(TimeStampedModel):
    """A separate request to cancel an already approved leave."""

    STATUS = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("withdrawn", "Withdrawn"),
    ]

    application = models.ForeignKey(
        LeaveApplication,
        on_delete=models.PROTECT,
        related_name="cancellations",
    )

    requested_by_user_id = models.IntegerField()
    requested_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

    status = models.CharField(
        max_length=12, choices=STATUS, default="pending", db_index=True
    )
    decided_by_user_id = models.IntegerField(null=True, blank=True)
    decided_by_role = models.CharField(max_length=100, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = "elm_leave_cancellation"
        indexes = [
            models.Index(
                fields=["application", "status"],
                name="elm_cancel_app_status_idx",
            ),
        ]

    def __str__(self):
        return f"Cancellation for application {self.application_id}"


class LeaveExtension(TimeStampedModel):
    """A separate request to extend an ongoing EL, COL or VL leave."""

    STATUS = [
        ("pending", "Pending"),
        ("applicant_action_required", "Applicant Action Required"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("withdrawn", "Withdrawn"),
    ]

    application = models.ForeignKey(
        LeaveApplication,
        on_delete=models.PROTECT,
        related_name="extensions",
    )

    requested_by_user_id = models.IntegerField()
    requested_start_date = models.DateField()
    requested_end_date = models.DateField()
    additional_chargeable_days = models.DecimalField(
        max_digits=7, decimal_places=2
    )
    reason = models.TextField()

    status = models.CharField(
        max_length=32, choices=STATUS, default="pending", db_index=True
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    decided_by_user_id = models.IntegerField(null=True, blank=True)
    decided_by_role = models.CharField(max_length=100, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = "elm_leave_extension"
        indexes = [
            models.Index(
                fields=["application", "status"],
                name="elm_ext_app_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    requested_end_date__gte=models.F(
                        "requested_start_date"
                    )
                ),
                name="elm_ext_valid_date_range",
            ),
            models.CheckConstraint(
                condition=Q(additional_chargeable_days__gt=0),
                name="elm_ext_positive_days",
            ),
        ]

    def __str__(self):
        return f"Extension for application {self.application_id}"


class LeaveResumption(TimeStampedModel):
    """Employee's actual resumption and authority review."""

    STATUS = [
        ("submitted", "Submitted"),
        ("under_review", "Under review"),
        ("reviewed", "Reviewed"),
    ]

    OUTCOME = [
        ("normal", "Normal resumption"),
        ("early", "Early resumption"),
        ("late", "Late resumption"),
    ]

    application = models.ForeignKey(
        LeaveApplication,
        on_delete=models.PROTECT,
        related_name="resumptions",
    )

    submitted_by_user_id = models.IntegerField()
    actual_resumption_date = models.DateField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=16, choices=STATUS, default="submitted", db_index=True
    )
    outcome = models.CharField(
        max_length=10, choices=OUTCOME, blank=True
    )

    reviewed_by_user_id = models.IntegerField(null=True, blank=True)
    reviewed_by_role = models.CharField(max_length=100, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    balance_adjustment_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0
    )
    attendance_sync_reference = models.CharField(max_length=160, blank=True)

    class Meta:
        db_table = "elm_leave_resumption"
        indexes = [
            models.Index(
                fields=["application", "status"],
                name="elm_resume_app_status_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["application"],
                name="elm_one_resumption_per_app",
            ),
        ]

    def __str__(self):
        return f"Resumption for application {self.application_id}"


# ---------------------------------------------------------------------------
# Holiday and Restricted Holiday calendar
# ---------------------------------------------------------------------------

class HolidayCalendar(TimeStampedModel):
    """A holiday/RH calendar; only a published calendar is effective."""

    STATUS = [
        ("draft", "Draft"),
        ("published", "Published"),
        ("superseded", "Superseded"),
    ]

    name = models.CharField(max_length=160)
    calendar_year = models.PositiveSmallIntegerField()
    effective_from = models.DateField()
    effective_to = models.DateField()

    status = models.CharField(
        max_length=12, choices=STATUS, default="draft", db_index=True
    )

    created_by_user_id = models.IntegerField()
    published_by_user_id = models.IntegerField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "elm_holiday_calendar"
        constraints = [
            models.UniqueConstraint(
                fields=["calendar_year"],
                condition=Q(status="published"),
                name="elm_one_published_calendar_year",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__gte=models.F("effective_from")),
                name="elm_calendar_valid_dates",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.calendar_year})"


class HolidayCalendarDate(models.Model):
    """A date in a holiday calendar, optionally designated as an RH."""

    calendar = models.ForeignKey(
        HolidayCalendar,
        on_delete=models.PROTECT,
        related_name="dates",
    )
    holiday_date = models.DateField()
    title = models.CharField(max_length=160)
    is_restricted_holiday = models.BooleanField(default=False)
    is_closed = models.BooleanField(default=True)

    class Meta:
        db_table = "elm_holiday_calendar_date"
        constraints = [
            models.UniqueConstraint(
                fields=["calendar", "holiday_date"],
                name="elm_calendar_date_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["holiday_date", "is_restricted_holiday"],
                name="elm_holiday_date_rh_idx",
            ),
        ]

    def __str__(self):
        return f"{self.holiday_date}: {self.title}"


# ---------------------------------------------------------------------------
# Current policy and hierarchy configuration
# ---------------------------------------------------------------------------

class LeavePolicyConfiguration(TimeStampedModel):
    """Current configured ELM policy/hierarchy values.

    This deliberately has no draft/publish/effective-version lifecycle.
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField(default=dict)
    description = models.CharField(max_length=300, blank=True)

    updated_by_user_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "elm_policy_configuration"

    def __str__(self):
        return self.key


# ---------------------------------------------------------------------------
# Offline-sanctioned leave synchronization
# ---------------------------------------------------------------------------

class OfflineSanctionRecord(TimeStampedModel):
    """Record an already-sanctioned leave from an authorized offline process."""

    STATUS = [
        ("recorded", "Recorded"),
        ("validated", "Validated"),
        ("synchronized", "Synchronized"),
        ("exception", "Exception"),
    ]

    application = models.OneToOneField(
        LeaveApplication,
        on_delete=models.PROTECT,
        related_name="offline_sanction_record",
    )

    recorded_by_user_id = models.IntegerField()
    sanctioning_authority_user_id = models.IntegerField(null=True, blank=True)
    sanctioning_authority_role = models.CharField(max_length=100, blank=True)

    offline_sanction_reference = models.CharField(max_length=160, unique=True)
    sanction_date = models.DateField()
    evidence_reference = models.CharField(max_length=500)
    evidence_metadata = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=16, choices=STATUS, default="recorded", db_index=True
    )
    validated_by_user_id = models.IntegerField(null=True, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    synchronized_at = models.DateTimeField(null=True, blank=True)
    exception_note = models.TextField(blank=True)

    class Meta:
        db_table = "elm_offline_sanction_record"

    def __str__(self):
        return self.offline_sanction_reference


# ---------------------------------------------------------------------------
# SLA configuration and action history
# ---------------------------------------------------------------------------

class SLAConfiguration(TimeStampedModel):
    """Configurable reminder and escalation thresholds."""

    ACTION = [
        ("reminder", "Reminder"),
        ("escalation", "Escalation"),
    ]

    ESCALATION_ACTION = [
        ("notify", "Notify only"),
        ("reroute", "Change routing/responsibility"),
    ]

    task_type = models.CharField(max_length=32)
    action = models.CharField(max_length=12, choices=ACTION)

    threshold_minutes = models.PositiveIntegerField()
    is_enabled = models.BooleanField(default=True)

    escalation_action = models.CharField(
        max_length=10,
        choices=ESCALATION_ACTION,
        default="notify",
    )
    target_role = models.CharField(max_length=100, blank=True)

    updated_by_user_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "elm_sla_configuration"
        constraints = [
            models.UniqueConstraint(
                fields=["task_type", "action"],
                name="elm_sla_task_action_unique",
            ),
            models.CheckConstraint(
                condition=Q(threshold_minutes__gt=0),
                name="elm_sla_threshold_positive",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(action="reminder")
                    | Q(escalation_action="notify")
                ),
                name="elm_sla_reminder_no_reroute",
            ),
        ]

    def __str__(self):
        return f"{self.task_type}: {self.action}"


class SLAActionLog(TimeStampedModel):
    """Audit of a reminder or escalation applied to a workflow task."""

    ACTION = [
        ("reminder", "Reminder"),
        ("escalation", "Escalation"),
    ]

    task = models.ForeignKey(
        LeaveWorkflowTask,
        on_delete=models.PROTECT,
        related_name="sla_actions",
    )

    action = models.CharField(max_length=12, choices=ACTION)
    threshold_minutes = models.PositiveIntegerField()
    performed_at = models.DateTimeField(auto_now_add=True)

    recipient_user_id = models.IntegerField(null=True, blank=True)
    recipient_role = models.CharField(max_length=100, blank=True)

    routing_changed = models.BooleanField(default=False)
    previous_assignee_user_id = models.IntegerField(null=True, blank=True)
    new_assignee_user_id = models.IntegerField(null=True, blank=True)

    dedupe_key = models.CharField(max_length=180, unique=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "elm_sla_action_log"
        indexes = [
            models.Index(
                fields=["task", "performed_at"],
                name="elm_sla_task_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.action} for task {self.task_id}"
