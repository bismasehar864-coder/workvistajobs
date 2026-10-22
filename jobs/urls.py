from django.urls import path
from . import views, views_employer, views_alerts, views_settings


urlpatterns = [

    # =====================================================
    # PUBLIC PAGES
    # =====================================================

    path(
        "",
        views.home,
        name="home"
    ),

    path(
        "jobs/<int:job_id>/",
        views.job_detail,
        name="job_detail"
    ),

    path(
        "jobs/<int:job_id>/save/",
        views.toggle_save_job,
        name="toggle_save_job"
    ),

    path(
        "jobs/<int:job_id>/apply/",
        views.apply_job,
        name="apply_job"
    ),

    path(
        "signin/",
        views.signin,
        name="signin"
    ),

    path(
        "signup/",
        views.signup_choose,
        name="signup"
    ),

    path(
        "signup/employee/",
        views.signup_employee,
        name="signup_employee"
    ),

    path(
        "signup/employer/",
        views.signup_employer,
        name="signup_employer"
    ),

    path(
        "cv_upload/",
        views.cv_upload,
        name="cv_upload"
    ),

    path(
        "preferences/",
        views.preferences,
        name="preferences"
    ),


    # =====================================================
    # DASHBOARD ROUTING
    # =====================================================

    path(
        "dashboard/",
        views.dashboard,
        name="dashboard"
    ),

    # USER DASHBOARD
    #
    # Every tab is a real address rather than a fragment, so clicking
    # updates the URL, reloading stays put, a link can be shared, and a
    # form can redirect back to the tab it lives in. The bare path opens
    # My Profile.
    path(
        "dashboard/user/",
        views.user_dashboard,
        name="user_dashboard"
    ),

    path(
        "dashboard/user/profile/",
        views.user_dashboard,
        {"section": "profile"},
        name="dashboard_profile"
    ),

    path(
        "dashboard/user/profile/edit/",
        views_settings.edit_profile,
        name="edit_profile"
    ),

    path(
        "dashboard/user/recommended/",
        views.user_dashboard,
        {"section": "recommended"},
        name="dashboard_recommended"
    ),

    path(
        "dashboard/user/trending/",
        views.user_dashboard,
        {"section": "trending"},
        name="dashboard_trending"
    ),

    path(
        "dashboard/user/search/",
        views.user_dashboard,
        {"section": "search"},
        name="dashboard_search"
    ),

    path(
        "dashboard/user/saved/",
        views.user_dashboard,
        {"section": "saved"},
        name="dashboard_saved"
    ),

    path(
        "dashboard/user/notifications/",
        views_alerts.dashboard_notifications,
        name="dashboard_notifications"
    ),

    path(
        "dashboard/user/settings/",
        views_settings.dashboard_settings,
        name="dashboard_settings"
    ),

    # ADMIN DASHBOARD
    path(
        "dashboard/admin/",
        views.admin_dashboard,
        name="admin_dashboard"
    ),

    path(
        "dashboard/admin/profile/",
        views.admin_profile,
        name="admin_profile"
    ),

    path(
        "dashboard/admin/profile/update/",
        views.admin_update_profile,
        name="admin_update_profile"
    ),

    path(
        "dashboard/manage-employers/",
        views.manage_employers,
        name="manage_employers"
    ),

    path(
        "dashboard/manage-employers/<int:job_id>/allow/",
        views.allow_employer_job,
        name="allow_employer_job"
    ),

    path(
        "dashboard/manage-employers/<int:job_id>/deny/",
        views.deny_employer_job,
        name="deny_employer_job"
    ),

    # SUPER ADMIN DASHBOARD
    path(
        "dashboard/superadmin/",
        views.superadmin_dashboard,
        name="superadmin_dashboard"
    ),

    path(
        "dashboard/superadmin/profile/",
        views.superadmin_profile,
        name="superadmin_profile"
    ),

    path(
        "dashboard/superadmin/profile/update/",
        views.superadmin_update_profile,
        name="superadmin_update_profile"
    ),


    # =====================================================
    # EMPLOYER DASHBOARD
    # =====================================================
    #
    # Same contract as the user dashboard: every section is a real
    # address, so clicking updates the URL, reloading stays put, and a
    # form redirects back to the section it lives in. The bare path
    # opens the company profile.

    path(
        "dashboard/employer/",
        views_employer.employer_dashboard,
        name="employer_dashboard"
    ),

    path(
        "dashboard/employer/company/",
        views_employer.employer_company,
        name="employer_company"
    ),

    path(
        "dashboard/employer/postings/",
        views_employer.employer_postings,
        name="employer_postings"
    ),

    path(
        "dashboard/employer/branches/",
        views_employer.employer_branches,
        name="employer_branches"
    ),

    path(
        "dashboard/employer/branches/<int:branch_id>/edit/",
        views_employer.employer_branch_edit,
        name="employer_branch_edit"
    ),

    path(
        "dashboard/employer/branches/<int:branch_id>/delete/",
        views_employer.employer_branch_delete,
        name="employer_branch_delete"
    ),

    path(
        "dashboard/employer/post-job/",
        views_employer.post_job,
        name="post_job"
    ),

    path(
        "dashboard/employer/post-job/<int:job_id>/edit/",
        views_employer.edit_posted_job,
        name="edit_posted_job"
    ),

    path(
        "dashboard/employer/post-job/<int:job_id>/delete/",
        views_employer.delete_posted_job,
        name="delete_posted_job"
    ),


    # =====================================================
    # USER DASHBOARD FEATURES
    # =====================================================

    path(
        "dashboard/trending/",
        views.trending_jobs,
        name="trending_jobs"
    ),

    path(
        "dashboard/search/",
        views.search_jobs,
        name="search_jobs"
    ),

    path(
        "dashboard/saved/",
        views.saved_jobs,
        name="saved_jobs"
    ),

    path(
        "dashboard/applied/",
        views.applied_jobs,
        name="applied_jobs"
    ),


    # =====================================================
    # SUPER ADMIN — ADMIN MANAGEMENT
    # =====================================================

    path(
        "dashboard/superadmin/add-admin/",
        views.add_admin,
        name="add_admin"
    ),

    path(
        "dashboard/superadmin/remove-admin/<int:user_id>/",
        views.remove_admin,
        name="remove_admin"
    ),


    # =====================================================
    # SUPER ADMIN — USER MANAGEMENT
    # =====================================================

    path(
        "dashboard/superadmin/delete-user/<int:user_id>/",
        views.delete_user,
        name="delete_user"
    ),


    # =====================================================
    # ADMIN — USER MANAGEMENT
    # =====================================================

    path(
        "dashboard/admin/delete-user/<int:user_id>/",
        views.admin_delete_user,
        name="admin_delete_user"
    ),


    # =====================================================
    # SCRAPER MANAGEMENT
    # =====================================================

    # Used by BOTH Admin and Super Admin
    path(
        "dashboard/superadmin/run-scraper/<str:scraper_name>/",
        views.run_scraper,
        name="run_scraper"
    ),


    # =====================================================
    # WEBSITE MANAGEMENT
    # =====================================================

    path(
        "delete-website/<int:id>/",
        views.delete_website,
        name="delete_website"
    ),


    # =====================================================
    # NOTIFICATIONS AND ALERTS
    # =====================================================

    path(
        "alerts/unsubscribe/<str:token>/",
        views_alerts.alerts_unsubscribe,
        name="alerts_unsubscribe"
    ),


    # =====================================================
    # AUTHENTICATION
    # =====================================================

    path(
        "accounts/login/",
        views.signin,
        name="login"
    ),

    path(
        "logout/",
        views.logout_view,
        name="logout"
    ),


    # =====================================================
    # CV
    # =====================================================

    path(
        "cv/edit/",
        views.edit_cv_data,
        name="edit_cv_data"
    ),
]
