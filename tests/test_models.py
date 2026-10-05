from sqlalchemy.orm import configure_mappers

import app.db.models  # noqa: F401 - registers every model


def test_orm_mappers_configure():
    """Every relationship()/back_populates pair must resolve. A typo here
    only fails on the first ORM query that touches the model, so check it
    up front -- this caught CustomerCredentials.customer pointing
    back_populates at a property that didn't exist."""
    configure_mappers()
