"""Tests cho rag.retriever - chỉ test phần pure (infer_topic, không cần Chroma)."""
from __future__ import annotations

from rag.retriever import infer_topic


def test_infer_topic_kubernetes():
    assert infer_topic("Pod là gì?") == "kubernetes"
    assert infer_topic("rbac authorization") == "kubernetes"
    assert infer_topic("Helm chart") == "kubernetes"


def test_infer_topic_react():
    assert infer_topic("useState dùng khi nào?") == "react"
    assert infer_topic("React component") == "react"
    assert infer_topic("Next.js routing") == "react"


def test_infer_topic_postgres():
    assert infer_topic("INNER JOIN khác LEFT JOIN") == "postgresql"
    assert infer_topic("postgres transaction") == "postgresql"


def test_infer_topic_docker():
    assert infer_topic("Docker compose") == "docker"
    assert infer_topic("Container image") == "docker"


def test_infer_topic_springboot():
    assert infer_topic("Spring Boot @RestController") == "springboot"
    assert infer_topic("JPA Hibernate") == "springboot"


def test_infer_topic_returns_none_for_offtopic():
    assert infer_topic("Thời tiết hôm nay thế nào?") is None
    assert infer_topic("xin chào") is None
