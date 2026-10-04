terraform {
  required_version = ">= 1.7.0"
  required_providers { google = { source = "hashicorp/google", version = "~> 7.0" } }
}
provider "google" { project = var.project_id region = var.region }
resource "google_project_service" "run" { service="run.googleapis.com" disable_on_destroy=false }
resource "google_project_service" "compute" { service="compute.googleapis.com" disable_on_destroy=false }
resource "google_project_service" "artifact" { service="artifactregistry.googleapis.com" disable_on_destroy=false }
resource "google_project_service" "firestore" { service="firestore.googleapis.com" disable_on_destroy=false }
resource "google_project_service" "secret" { service="secretmanager.googleapis.com" disable_on_destroy=false }
resource "google_artifact_registry_repository" "minehub" {
  location=var.region repository_id="minehub" format="DOCKER"
  depends_on=[google_project_service.artifact]
}
resource "google_service_account" "control" { account_id="minehub-control" display_name="MineHub Cloud Run control plane" }
resource "google_project_iam_member" "compute_admin" {
  project=var.project_id role="roles/compute.instanceAdmin.v1"
  member=format("serviceAccount:%s",google_service_account.control.email)
}
resource "google_project_iam_member" "compute_network" {
  project=var.project_id role="roles/compute.networkAdmin"
  member=format("serviceAccount:%s",google_service_account.control.email)
}
resource "google_project_iam_member" "artifact_reader" {
  project=var.project_id role="roles/artifactregistry.reader"
  member=format("serviceAccount:%s",google_service_account.control.email)
}
resource "google_secret_manager_secret" "admin" {
  secret_id="minehub-admin-token" replication { auto {} }
  depends_on=[google_project_service.secret]
}
resource "google_secret_manager_secret_iam_member" "admin_reader" {
  secret_id=google_secret_manager_secret.admin.id role="roles/secretmanager.secretAccessor"
  member=format("serviceAccount:%s",google_service_account.control.email)
}
resource "google_firestore_database" "default" {
  project=var.project_id name="(default)" location_id=var.region type="FIRESTORE_NATIVE"
  depends_on=[google_project_service.firestore]
}
resource "google_compute_firewall" "minecraft" {
  name="minehub-minecraft" network="default" direction="INGRESS"
  source_ranges=["0.0.0.0/0"] target_tags=["minehub-minecraft"]
  allow { protocol="tcp" ports=["25565"] }
}
output "control_service_account" { value=google_service_account.control.email }
output "artifact_repository" { value=google_artifact_registry_repository.minehub.name }

resource "google_project_iam_member" "firestore_user" {
  project=var.project_id
  role="roles/datastore.user"
  member=format("serviceAccount:%s",google_service_account.control.email)
}
resource "google_project_iam_member" "service_account_user" {
  project=var.project_id
  role="roles/iam.serviceAccountUser"
  member=format("serviceAccount:%s",google_service_account.control.email)
}
resource "google_cloud_run_v2_service" "control" {
  name="minehub-control"
  location=var.region
  ingress="INGRESS_TRAFFIC_ALL"
  deletion_protection=false
  template {
    service_account=google_service_account.control.email
    timeout="3600s"
    scaling { min_instance_count=1 max_instance_count=3 }
    containers {
      image=var.image
      ports { container_port=8080 }
      env { name="GOOGLE_CLOUD_PROJECT" value=var.project_id }
      env { name="GOOGLE_CLIENT_ID" value=var.google_client_id }
      env { name="COMPUTE_ZONE" value="asia-south1-a" }
      env { name="COMPUTE_NETWORK" value="default" }
      env { name="MINECRAFT_MACHINE_TYPE" value="e2-small" }
      env { name="MINECRAFT_DISK_GB" value="20" }
      env { name="CONTROL_URL" value="https://PLACEHOLDER" }
      env { name="CORS_ORIGINS" value="*" }
    }
  }
  depends_on=[google_project_service.run,google_project_service.compute,google_project_service.firestore]
}
resource "google_cloud_run_v2_service_iam_member" "public" {
  name=google_cloud_run_v2_service.control.name
  location=google_cloud_run_v2_service.control.location
  role="roles/run.invoker"
  member="allUsers"
}
output "control_url" { value=google_cloud_run_v2_service.control.uri }
