from enum import Enum, StrEnum, auto
from typing import Optional
from datetime import date

import json
from sqlalchemy import Enum as SAEnum, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    type_annotation_map = {
        Enum: SAEnum(Enum, validate_strings=True),
    }


class Group(Enum):
    PPE = "Groupe du Parti populaire européen (Démocrates-Chrétiens)"
    RE = "Groupe Renew Europe"
    GUE = "Le groupe de la gauche au Parlement européen - GUE/NGL"
    ID = "Groupe «Identité et démocratie»"
    VALE = "Groupe des Verts/Alliance libre européenne"
    SD = "Groupe de l'Alliance Progressiste des Socialistes et Démocrates au Parlement européen"
    ECR = "Groupe des Conservateurs et Réformistes européens"
    NA = "Non-inscrits"

    @classmethod
    def from_str(cls, s):
        match s:
            case "Verts/ALE":
                s = "VALE"
            case "PPE-DE":
                s = "PPE"
            case 'GUE/NGL':
                s = "GUE"
            case 'S&D':
                s = "SD"
        return cls[s]


class Committee(Enum):
    AFET = "Committee on Foreign Affairs"
    DEFE = "Subcommittee on Security and Defence"
    DROI = "Subcommittee on Human Rights"
    DEVE = "Committee on Development"
    INTA = "Committee on International Trade"
    BUDG = "Committee on Budgets"
    CONT = "Committee on Budgetary Control"
    ECON = "Committee on Economic and Monetary Affairs"
    FISC = "Subcommittee on Tax Matters"
    EMPL = "Committee on Employment and Social Affairs"
    ENVI = "Committee on Environment, Public Health and Food Safety"
    ITRE = "Committee on Industry, Research and Energy"
    IMCO = "Committee on Internal Market and Consumer Protection"
    TRAN = "Committee on Transport and Tourism"
    REGI = "Committee on Regional Development"
    AGRI = "Committee on Agriculture and Rural Development"
    PECH = "Committee on Fisheries"
    CULT = "Committee on Culture and Education"
    JURI = "Committee on Legal Affairs"
    LIBE = "Committee on Civil Liberties, Justice and Home Affairs"
    AFCO = "Committee on Constitutional Affairs"
    FEMM = "Committee on Women's Rights and Gender Equality"
    PETI = "Committee on Petitions"


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str]
    group: Mapped[Group]
    party: Mapped[str]


class Procedure(Base):
    __tablename__ = "procedures"

    class Type(Enum):
        RSP = "Resolutions on topical subjects"
        INS = "Institutional procedure"
        NLE = "Non-legislative enactments"
        COD = "Ordinary legislative procedure (ex-codecision procedure)"
        JOIN = "Joint document from the Commission and the High Representative"
        INI = "Own-initiative procedure"
        BUI = "Budgetary initiative"
        CNS = "Consultation procedure"
        RPS = "Implementing acts"
        INL = "Legislative initiative procedure"
        APP = "Consent procedure"
        ACI = "Interinstitutional agreement procedure"
        SWD = "Commission working document"
        BUD = "Budgetary procedure"
        DEA = "Delegated acts procedure"
        C = "Other Commission document"
        COM = "Commission document"
        DEC = "Discharge procedure"
        RSO = "Internal organisation decisions"
        REG = "Parliament's Rules of Procedure"
        IMM = "Members' immunity"

        @classmethod
        def from_str(cls, s):
            return cls[s.split(" ")[0]]

    reference: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
    type: Mapped[Type]
    subject: Mapped[str]
    date: Mapped[date]
    url: Mapped[str]

class Amendment(Base):
    __tablename__ = "amendments"

    id: Mapped[str] = mapped_column(primary_key=True)
    procedure_ref = mapped_column(ForeignKey(Procedure.reference))
    old: Mapped[Optional[str]]
    new: Mapped[Optional[str]]


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    procedure_ref = mapped_column(ForeignKey(Procedure.reference))
    amendment_id = mapped_column(ForeignKey(Amendment.id))
    title: Mapped[str]
    positions: Mapped[list[dict]] = mapped_column(JSON)
    date: Mapped[date]


class Position(Base):
    __tablename__ = "positions"

    class Position(StrEnum):
        FOR = auto()
        AGAINST = auto()
        ABSTENTION = auto()
        NOVOTE = auto()

        @classmethod
        def from_str(cls, s: str):
            match s:
                case "+":
                    return cls.FOR
                case "-":
                    return cls.AGAINST
                case "0":
                    return cls.ABSTENTION

    vote_id: Mapped[int] = mapped_column(ForeignKey(Vote.id), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey(Member.id), primary_key=True)
    position: Mapped[Position]
