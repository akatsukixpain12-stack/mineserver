# MineHub infrastructure

Terraform provisions the real Google Cloud foundation for MineHub: required APIs, Artifact Registry, Firestore Native, Secret Manager, a dedicated control-plane service account and the Minecraft TCP firewall rule.

Run:
terraform init
terraform plan -var="project_id=YOUR_PROJECT"
terraform apply -var="project_id=YOUR_PROJECT"

The generated Cloud Run service account needs Compute Engine permissions because the control plane creates and controls Minecraft VMs. Tighten the IAM role to a custom least-privilege role before opening the service publicly.
