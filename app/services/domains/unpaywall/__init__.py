from __future__ import annotations


async def resolve_publication_pdf_urls(*args, **kwargs):
    from app.services.domains.unpaywall.application import resolve_publication_pdf_urls as _impl

    return await _impl(*args, **kwargs)


__all__ = ["resolve_publication_pdf_urls"]
