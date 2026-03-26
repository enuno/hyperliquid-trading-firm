# Terraform and Kubernetes — multi-cloud friendly skeleton
# Add required_providers and backend per cloud (AWS, GCP, Azure, etc.)

terraform {
  required_version = ">= 1.0"

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    # Example: Kubernetes provider (use when targeting a real cluster)
    # kubernetes = {
    #   source  = "hashicorp/kubernetes"
    #   version = "~> 2.23"
    # }
    # Example: AWS for EKS
    # aws = {
    #   source  = "hashicorp/aws"
    #   version = "~> 5.0"
    # }
  }

  # Uncomment and set backend when using remote state (e.g. S3, GCS)
  # backend "s3" {
  #   bucket         = "your-tfstate-bucket"
  #   key            = "terraform01/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

# Placeholder so validate succeeds without cloud creds
resource "null_resource" "skeleton" {
  triggers = {
    repo = "terraform01"
  }
}
