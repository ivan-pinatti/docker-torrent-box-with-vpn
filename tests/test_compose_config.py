from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent


def test_audiobookshelf_mounts_full_metadata_tree():
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose-media-library.yml").read_text()
    )
    volumes = compose["services"]["audiobookshelf"]["volumes"]

    assert "${CONFIG_FOLDER}/audiobookshelf/metadata:/metadata:z" in volumes


def test_homepage_whisparr_uses_radarr_widget():
    services = yaml.safe_load(
        (REPO_ROOT / "configs/homepage/config/services.yaml").read_text()
    )
    servarr_group = next(group["Servarr"] for group in services if "Servarr" in group)
    whisparr = next(
        service["Whisparr"] for service in servarr_group if "Whisparr" in service
    )

    assert whisparr["widget"]["type"] == "radarr"


def test_homepage_calibreweb_widget_and_cadvisor_link():
    services = yaml.safe_load(
        (REPO_ROOT / "configs/homepage/config/services.yaml").read_text()
    )
    media_group = next(
        group["Media & Library"] for group in services if "Media & Library" in group
    )
    calibre_web = next(
        service["Calibre Web"] for service in media_group if "Calibre Web" in service
    )
    observability_group = next(
        group["Observability"] for group in services if "Observability" in group
    )
    cadvisor = next(
        service["cAdvisor"] for service in observability_group if "cAdvisor" in service
    )

    assert calibre_web["widget"]["type"] == "calibreweb"
    assert cadvisor["href"] == "/admin/cadvisor/containers/"


def test_homepage_footer_shows_version():
    settings = yaml.safe_load(
        (REPO_ROOT / "configs/homepage/config/settings.yaml").read_text()
    )

    assert settings["hideVersion"] is False


def test_homepage_group_and_media_ordering():
    services = yaml.safe_load(
        (REPO_ROOT / "configs/homepage/config/services.yaml").read_text()
    )
    group_names = [next(iter(group)) for group in services]
    indexers_downloaders = next(
        group["Indexers & Downloaders"]
        for group in services
        if "Indexers & Downloaders" in group
    )
    media_group = next(
        group["Media & Library"] for group in services if "Media & Library" in group
    )

    assert "Indexers" not in group_names
    assert "Downloads" not in group_names
    assert [next(iter(service)) for service in indexers_downloaders] == [
        "qBittorrent",
        "SABnzbd",
        "Prowlarr",
        "NZBHydra2",
        "JDownloader2",
    ]

    media_services = [next(iter(service)) for service in media_group]
    assert media_services.index("Calibre Web") < media_services.index("Calibre")


def test_homepage_observability_widgets():
    services = yaml.safe_load(
        (REPO_ROOT / "configs/homepage/config/services.yaml").read_text()
    )
    observability_group = next(
        group["Observability"] for group in services if "Observability" in group
    )
    grafana = next(
        service["Grafana"] for service in observability_group if "Grafana" in service
    )
    prometheus = next(
        service["Prometheus"]
        for service in observability_group
        if "Prometheus" in service
    )

    assert grafana["widget"] == {
        "type": "grafana",
        "url": "http://grafana:3000/admin/grafana",
        "version": 2,
        "alerts": "grafana",
        "headers": {
            "Authorization": "{{HOMEPAGE_FILE_GRAFANA_AUTH}}",
        },
    }
    assert prometheus["widget"] == {
        "type": "prometheus",
        "url": "http://prometheus:9090/admin/prometheus",
    }
