"""Support for image entities."""

from homeassistant.components.image import DOMAIN as ENTITY_DOMAIN

from .helpers import Helper

async_setup_entry = Helper.async_setup_entry_for(ENTITY_DOMAIN)
