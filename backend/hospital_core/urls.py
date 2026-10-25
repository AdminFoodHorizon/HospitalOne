from django.urls import path

from . import hospital_email_views
from . import hospital_admin_views
from . import reception_direct_email_views

from . import (
    views,
    public_views,
    reception_views,
    announcement_called_views,
    nursing_views,
    display_views,
    doctor_views,
    investigation_reception_views,
    investigation_views,
    investigation_report_views,
    pharmacy_views,
)

from . import reception_messaging_views

urlpatterns = [
    # General hospital notices; separate from automatic patient calls.
    # Hospital administrator — additive, 2FA and tenant scoped.
    path('<slug:slug>/admin/finances/', hospital_admin_views.finances),
    path('<slug:slug>/admin/archive/', hospital_admin_views.archive),
    path('<slug:slug>/admin/catalog/<str:kind>/create/', hospital_admin_views.catalog_create),
    path('<slug:slug>/admin/overview/', hospital_admin_views.overview),
    path('<slug:slug>/admin/staff/', hospital_admin_views.staff),
    path('<slug:slug>/admin/staff/create/', hospital_admin_views.staff_create),
    path('<slug:slug>/admin/staff/<int:membership_id>/action/', hospital_admin_views.staff_action),
    path('<slug:slug>/admin/departments/', hospital_admin_views.departments),
    path('<slug:slug>/admin/departments/create/', hospital_admin_views.department_create),
    path('<slug:slug>/admin/catalog/<str:kind>/', hospital_admin_views.catalog),
    path('<slug:slug>/admin/catalog/<str:kind>/<int:item_id>/update/', hospital_admin_views.catalog_update),
    path('<slug:slug>/admin/patients/', hospital_admin_views.patient_search),
    path('<slug:slug>/admin/patients/<int:patient_id>/', hospital_admin_views.patient_detail),
    path('<slug:slug>/admin/history/<str:kind>/', hospital_admin_views.history),
    path('<slug:slug>/admin/devices/', hospital_admin_views.display_admin_status),

    path('<slug:slug>/pharmacy/queue/', pharmacy_views.queue, name='hospital-pharmacy-queue'),
    path('<slug:slug>/pharmacy/visits/<int:visit_id>/', pharmacy_views.detail, name='hospital-pharmacy-detail'),
    path('<slug:slug>/pharmacy/visits/<int:visit_id>/finalize/', pharmacy_views.finalize, name='hospital-pharmacy-finalize'),
    path('<slug:slug>/reception/patient-history/', pharmacy_views.reception_patient_history, name='reception-patient-history'),
    path('<slug:slug>/reception/patient-history/<int:patient_id>/visits/', pharmacy_views.reception_patient_visits, name='reception-patient-visits'),
    path('<slug:slug>/reception/visit-history/<int:visit_id>/', pharmacy_views.reception_visit_history_detail, name='reception-visit-history-detail'),
    path('<slug:slug>/reception/pharmacy-completed/', pharmacy_views.reception_queue, name='hospital-reception-pharmacy-completed'),
    path('<slug:slug>/reception/pharmacy-completed/<int:visit_id>/', pharmacy_views.reception_summary, name='hospital-reception-pharmacy-summary'),
    path('<slug:slug>/reception/pharmacy-completed/<int:visit_id>/finalize/', pharmacy_views.reception_finalize, name='hospital-reception-pharmacy-finalize'),

    # Common Investigation Dashboard (Laboratory, Radiology, ECG)
    path('<slug:slug>/investigations/queue/', investigation_views.queue, name='hospital-investigation-queue'),
    path('<slug:slug>/investigations/reports/completed/', investigation_views.completed_reports, name='hospital-investigation-completed-reports'),
    path('<slug:slug>/investigations/queue/<int:entry_id>/call/', investigation_views.call, name='hospital-investigation-call'),
    path('<slug:slug>/investigations/queue/<int:entry_id>/recall-pending/', investigation_views.recall_pending, name='hospital-investigation-recall'),
    path('<slug:slug>/investigations/queue/<int:entry_id>/start/', investigation_views.start, name='hospital-investigation-start'),
    path('<slug:slug>/investigations/items/<int:item_id>/result/', investigation_report_views.legacy_result_guard, name='hospital-investigation-result'),



    path('<slug:slug>/investigations/queue/<int:entry_id>/release/',
         investigation_views.release_patient, name='investigation-release-patient'),
    path('<slug:slug>/investigations/queue/<int:entry_id>/complete-testing/',
         investigation_views.complete_testing, name='investigation-complete-testing'),
    path('<slug:slug>/investigations/items/<int:item_id>/structured-report/pdf/',
         investigation_report_views.download_pdf, name='investigation-report-pdf'),

    # Stage 5B1 structured reports: separate from legacy finalization endpoint
    path('<slug:slug>/investigations/items/<int:item_id>/structured-report/',
         investigation_report_views.report_detail, name='investigation-structured-report'),
    path('<slug:slug>/investigations/items/<int:item_id>/structured-report/draft/',
         investigation_report_views.save_draft, name='investigation-structured-report-draft'),

    path('<slug:slug>/investigations/items/<int:item_id>/structured-report/complete/',
         investigation_report_views.complete_report, name='investigation-report-complete'),
    path('<slug:slug>/investigations/items/<int:item_id>/complete-test/',
         investigation_report_views.complete_report, name='investigation-complete-test'),
    path('<slug:slug>/investigations/items/<int:item_id>/structured-report/submit/',
         investigation_report_views.submit_review, name='investigation-report-submit'),
    path('<slug:slug>/investigations/items/<int:item_id>/structured-report/verify/',
         investigation_report_views.verify_release, name='investigation-report-verify'),

    # Reception investigation billing (same Reception dashboard)
    path('<slug:slug>/reception/investigation-bills/',
         investigation_reception_views.bills, name='reception-investigation-bills'),
    path('<slug:slug>/reception/investigation-bills/<int:bill_id>/call/',
         investigation_reception_views.call, name='reception-investigation-call'),
    path('<slug:slug>/reception/investigation-bills/<int:bill_id>/recall-pending/',
         investigation_reception_views.recall_pending, name='reception-investigation-recall-pending'),
    path('<slug:slug>/reception/investigation-bills/<int:bill_id>/release/',
         investigation_reception_views.release, name='reception-investigation-release'),


    # Public hospital information
    path('<slug:slug>/public-info/', public_views.hospital_public_info, name='hospital-public-info'),

    # Staff authentication and 2FA
    path('csrf/', views.csrf, name='hospital-csrf'),
    path('<slug:slug>/login/', views.password_login, name='hospital-login'),
    path('<slug:slug>/2fa/enroll/', views.enroll_start, name='hospital-2fa-enroll'),
    path('<slug:slug>/2fa/confirm/', views.enroll_confirm, name='hospital-2fa-confirm'),
    path('<slug:slug>/2fa/verify/', views.verify_login, name='hospital-2fa-verify'),
    path('<slug:slug>/2fa/recovery-login/', views.recovery_login, name='hospital-2fa-recovery'),
    path('<slug:slug>/me/', views.me, name='hospital-me'),
    path('<slug:slug>/logout/', views.staff_logout, name='hospital-logout'),

    # Reception: all views live in reception_views.py
    path('<slug:slug>/reception/investigation-reports/',
         reception_views.completed_investigation_visits,
         name='hospital-reception-investigation-reports'),
    path('<slug:slug>/reception/visits/<int:visit_id>/review-reports/',
         reception_views.review_investigation_reports,
         name='hospital-reception-review-reports'),
    path('<slug:slug>/reception/visits/<int:visit_id>/reassign-doctor/',
         reception_views.reassign_doctor,
         name='hospital-reception-reassign-doctor'),
    path('<slug:slug>/reception/doctors/', reception_views.doctors, name='hospital-reception-doctors'),
    path('<slug:slug>/reception/visits/', reception_views.visits, name='hospital-reception-visits'),
    path('<slug:slug>/reception/register/', reception_views.register_visit, name='hospital-reception-register'),
    path('<slug:slug>/reception/patients/search/', reception_views.search_patients, name='reception_patient_search'),
    path(
        '<slug:slug>/reception/visits/<int:visit_id>/return-for-review/',
        reception_views.confirm_return_for_review,
        name='hospital-reception-return-for-review',
    ),

    # Staff announcement history
    path('<slug:slug>/announcement/queue/', announcement_called_views.called_queue, name='hospital-announcement-queue'),

    # Nursing
    path('<slug:slug>/nursing/queue/', nursing_views.waiting_queue, name='hospital-nursing-queue'),
    path('<slug:slug>/nursing/queue/<int:entry_id>/call/', nursing_views.call_patient, name='hospital-nursing-call'),
    path('<slug:slug>/nursing/queue/<int:entry_id>/start/', nursing_views.start_assessment, name='hospital-nursing-start'),
    path('<slug:slug>/nursing/queue/<int:entry_id>/assessment/', nursing_views.save_assessment, name='hospital-nursing-assessment'),
    path('<slug:slug>/nursing/queue/<int:entry_id>/complete/', nursing_views.complete_nursing, name='hospital-nursing-complete'),

    # Central TV / display pairing
    path('<slug:slug>/announcement/display/pairing/request/', display_views.request_display_pairing, name='display-pairing-request'),
    path('<slug:slug>/announcement/display/pairing/approve/', display_views.approve_display_pairing, name='display-pairing-approve'),
    path('<slug:slug>/announcement/display/pairing/claim/', display_views.claim_display_pairing, name='display-pairing-claim'),
    path('<slug:slug>/announcement/display/events/', display_views.display_announcements, name='display-events'),
    path('<slug:slug>/announcement/display/revoke/', display_views.revoke_display, name='display-revoke'),

    # Doctor
    path('<slug:slug>/doctor/queue/', doctor_views.queue, name='hospital-doctor-queue'),
    path('<slug:slug>/doctor/queue/<int:entry_id>/call/', doctor_views.call_patient, name='hospital-doctor-call'),
    path('<slug:slug>/doctor/queue/<int:entry_id>/recall/', doctor_views.recall_patient, name='hospital-doctor-recall'),
    path('<slug:slug>/doctor/queue/<int:entry_id>/start/', doctor_views.start_consultation, name='hospital-doctor-start'),

    # Doctor active consultations and consultation editor (restored)
    path('<slug:slug>/doctor/consultations/<int:consultation_id>/reports/<int:item_id>/pdf/',
         doctor_views.consultation_report_pdf, name='hospital-doctor-report-pdf'),
    path('<slug:slug>/doctor/consultations/active/',
         doctor_views.active_consultations, name='hospital-doctor-active-consultations'),
    path('<slug:slug>/doctor/consultations/catalog/',
         doctor_views.consultation_catalog, name='hospital-doctor-consultation-catalog'),
    path('<slug:slug>/doctor/consultations/<int:consultation_id>/',
         doctor_views.consultation_detail, name='hospital-doctor-consultation-detail'),
    path('<slug:slug>/doctor/consultations/<int:consultation_id>/save/',
         doctor_views.save_consultation, name='hospital-doctor-consultation-save'),
    path('<slug:slug>/doctor/consultations/<int:consultation_id>/send-for-tests/',
         doctor_views.send_for_tests, name='hospital-doctor-send-for-tests'),
    path('<slug:slug>/doctor/consultations/<int:consultation_id>/finish/',
         doctor_views.finish_consultation, name='hospital-doctor-consultation-finish'),

    path('<slug:slug>/reception/report-delivery/', reception_messaging_views.report_delivery, name='reception-report-delivery'),
    # Send finalized investigation PDF directly through hospital Gmail.
    path('<slug:slug>/reception/investigation-reports/<int:item_id>/email-pdf/',
         reception_direct_email_views.send_reception_report_pdf,
         name='hospital-reception-email-report-pdf'),
    path('<slug:slug>/email/settings/', hospital_email_views.email_settings, name='hospital-email-settings'),
    path('<slug:slug>/email/settings/save/', hospital_email_views.save_email_settings, name='hospital-email-save'),
    path('<slug:slug>/email/settings/test/', hospital_email_views.test_email_settings, name='hospital-email-test'),
]
