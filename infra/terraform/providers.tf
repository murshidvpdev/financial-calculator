# =============================================================================
# PROVIDERS — Tell Terraform which cloud APIs to talk to
# =============================================================================
# Terraform uses "providers" as plugins to interact with cloud APIs.
# Each provider is downloaded by `terraform init` from the Terraform Registry.
#
# Why pin versions?
#   Without version pins, `terraform init` would pull the latest provider.
#   A breaking provider update could silently destroy your infrastructure.
#   Always pin to a known-good version and upgrade intentionally.
#
# AWS Provider docs: https://registry.terraform.io/providers/hashicorp/aws
# =============================================================================

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # =============================================================================
  # REMOTE STATE — Store terraform.tfstate in S3 (not on your laptop)
  # =============================================================================
  # Why remote state?
  #   - Local state: only you can run terraform, no team collaboration
  #   - S3 state: shared, versioned, recoverable, team-friendly
  #   - DynamoDB lock: prevents two people running terraform at the same time
  #     (without locking, simultaneous runs corrupt state)
  #
  # Create the bucket and table ONCE manually before using this:
  #   aws s3 mb s3://finance-calculator-tfstate --region us-east-1
  #   aws s3api put-bucket-versioning --bucket finance-calculator-tfstate \
  #     --versioning-configuration Status=Enabled
  #   aws dynamodb create-table --table-name finance-calculator-tflock \
  #     --attribute-definitions AttributeName=LockID,AttributeType=S \
  #     --key-schema AttributeName=LockID,KeyType=HASH \
  #     --billing-mode PAY_PER_REQUEST --region us-east-1
  # =============================================================================
  backend "s3" {
    bucket         = "finance-calculator-tfstate"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "finance-calculator-tflock"
  }
}

provider "aws" {
  region = var.aws_region

  # All resources created by Terraform get these tags automatically.
  # This makes it easy to find + filter all resources for this project in AWS Console.
  default_tags {
    tags = {
      Project     = "finance-calculator"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "murshidveypey790@gmail.com"
    }
  }
}
