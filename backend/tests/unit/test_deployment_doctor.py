"""Tests for Deployment Doctor Agent in-process validators."""

import pytest
from app.agents.deployment_doctor import DeploymentDoctorAgent


class TestDockerfileValidation:
    def setup_method(self):
        self.agent = DeploymentDoctorAgent.__new__(DeploymentDoctorAgent)

    def test_detects_latest_tag(self):
        result = self.agent._validate_dockerfile("FROM python:latest\nRUN pip install flask")
        issues = [i for i in result["issues"] if "latest" in i["message"].lower()]
        assert len(issues) > 0

    def test_detects_curl_pipe_to_shell(self):
        result = self.agent._validate_dockerfile("FROM python:3.12\nRUN curl https://example.com | sh")
        issues = [i for i in result["issues"] if "curl" in i["message"].lower()]
        assert len(issues) > 0
        assert issues[0]["severity"] == "critical"

    def test_detects_root_user(self):
        result = self.agent._validate_dockerfile("FROM python:3.12\nUSER root\nRUN apt-get update")
        issues = [i for i in result["issues"] if "root" in i["message"].lower()]
        assert len(issues) > 0

    def test_detects_secrets_in_env(self):
        result = self.agent._validate_dockerfile("FROM python:3.12\nENV DB_PASSWORD=hunter2")
        issues = [i for i in result["issues"] if "secret" in i["message"].lower()]
        assert len(issues) > 0

    def test_valid_dockerfile_passes(self):
        dockerfile = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
USER appuser
CMD ["python", "main.py"]"""
        result = self.agent._validate_dockerfile(dockerfile)
        critical = [i for i in result["issues"] if i["severity"] == "critical"]
        assert len(critical) == 0


class TestK8sValidation:
    def setup_method(self):
        self.agent = DeploymentDoctorAgent.__new__(DeploymentDoctorAgent)

    def test_detects_missing_resources(self):
        manifest = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: app
          image: myapp:latest
"""
        result = self.agent._validate_k8s_manifest(manifest)
        issues = [i for i in result["issues"] if "resource" in i["message"].lower()]
        assert len(issues) > 0

    def test_detects_unpinned_image(self):
        manifest = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: app
          image: myapp:latest
          resources:
            limits:
              cpu: "1"
              memory: "512Mi"
"""
        result = self.agent._validate_k8s_manifest(manifest)
        issues = [i for i in result["issues"] if "unpinned" in i["message"].lower()]
        assert len(issues) > 0

    def test_invalid_yaml(self):
        result = self.agent._validate_k8s_manifest("not: valid: yaml: [")
        assert result["valid"] is False


class TestTerraformValidation:
    def setup_method(self):
        self.agent = DeploymentDoctorAgent.__new__(DeploymentDoctorAgent)

    def test_detects_open_cidr(self):
        tf = 'resource "aws_security_group" "open" { ingress { cidr_blocks = ["0.0.0.0/0"] } }'
        result = self.agent._validate_terraform(tf)
        assert len(result["issues"]) > 0

    def test_detects_public_acl(self):
        tf = 'resource "aws_s3_bucket_acl" "public" { acl = "public-read" }'
        result = self.agent._validate_terraform(tf)
        issues = [i for i in result["issues"] if "public" in i["message"].lower()]
        assert len(issues) > 0
