variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for ALB"
  type        = list(string)
}

variable "enable_https" {
  description = "Provision an ACM cert + HTTPS:443 listener and redirect HTTP->HTTPS. Requires alb_domain_name and route53_zone_name."
  type        = bool
  default     = false
}

variable "alb_domain_name" {
  description = "Fully-qualified domain name to serve the app on (e.g. staging.example.com). Used for the ACM cert and Route53 alias."
  type        = string
  default     = ""
}

variable "route53_zone_name" {
  description = "Route53 hosted zone name that contains alb_domain_name (e.g. example.com). Trailing dot optional."
  type        = string
  default     = ""
}
