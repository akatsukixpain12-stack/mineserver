variable "project_id" { type=string description="Google Cloud project ID" }
variable "region" { type=string default="asia-south1" }
variable "google_client_id" { type=string description="Google Identity Services Web OAuth client ID" }
variable "image" { type=string description="Artifact Registry image for MineHub control plane" }
