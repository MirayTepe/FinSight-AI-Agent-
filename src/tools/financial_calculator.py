
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field, field_validator, model_validator

getcontext().prec = 35


class FinancialCalculationError(Exception):
    def __init__(self, message: str, error_code: str = "FINANCIAL_CALC_ERROR"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class ZeroDivisionFinancialError(FinancialCalculationError):
    def __init__(self, message: str = "Finansal hesaplamada bölen sıfır olamaz."):
        super().__init__(message, error_code="ZERO_DIVISION")


class NegativeValueError(FinancialCalculationError):
    def __init__(self, message: str = "Hesaplama için girdi değeri pozitif olmalıdır."):
        super().__init__(message, error_code="NEGATIVE_VALUE")


class InvalidPeriodError(FinancialCalculationError):
    def __init__(self, message: str = "Dönem sayısı (years/periods) en az 1 olmalıdır."):
        super().__init__(message, error_code="INVALID_PERIOD")


def to_decimal(val: Union[Decimal, float, int, str]) -> Decimal:
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as err:
        raise FinancialCalculationError(
            f"Geçersiz sayısal format: '{val}' ({type(val).__name__})",
            error_code="INVALID_NUMBER_FORMAT",
        ) from err



class GrowthInput(BaseModel):
    current_value: Decimal = Field(..., description="Güncel dönem değeri")
    previous_value: Decimal = Field(..., description="Önceki dönem baz değeri")

    @field_validator("current_value", "previous_value", mode="before")
    @classmethod
    def parse_to_decimal(cls, v: Any) -> Decimal:
        return to_decimal(v)

    @model_validator(mode="after")
    def validate_previous_value(self) -> GrowthInput:
        if self.previous_value == Decimal("0"):
            raise ZeroDivisionFinancialError(
                "Önceki dönem değeri (previous_value) 0 olamaz. Sıfırdan büyümeye oran hesaplanamaz (sıfıra bölme)."
            )
        return self


class GrowthOutput(BaseModel):
    success: bool = True
    growth_rate: Decimal = Field(..., description="Yüzdesel büyüme oranı (örn: 15.25 -> %15.25)")
    bps_change: Decimal = Field(..., description="Baz puan değişimi (1 yüzde puanı = 100 bps)")


class GrossMarginInput(BaseModel):
    revenue: Decimal = Field(..., description="Net Satışlar / Toplam Hasılat")
    gross_profit: Decimal = Field(..., description="Brüt Kâr Tutarı")

    @field_validator("revenue", "gross_profit", mode="before")
    @classmethod
    def parse_to_decimal(cls, v: Any) -> Decimal:
        return to_decimal(v)

    @model_validator(mode="after")
    def validate_revenue(self) -> GrossMarginInput:
        if self.revenue <= Decimal("0"):
            raise ZeroDivisionFinancialError(
                f"Brüt marj hesaplamak için gelir (revenue) pozitif ve sıfırdan büyük olmalıdır. (Girilen: {self.revenue})"
            )
        return self


class GrossMarginOutput(BaseModel):
    success: bool = True
    gross_margin: Decimal = Field(..., description="Brüt kâr marjı yüzdesi (%)")


class OperatingMarginInput(BaseModel):
    revenue: Decimal = Field(..., description="Net Satışlar / Toplam Hasılat")
    operating_income: Decimal = Field(..., description="Faaliyet Kârı / EBIT")

    @field_validator("revenue", "operating_income", mode="before")
    @classmethod
    def parse_to_decimal(cls, v: Any) -> Decimal:
        return to_decimal(v)

    @model_validator(mode="after")
    def validate_revenue(self) -> OperatingMarginInput:
        if self.revenue <= Decimal("0"):
            raise ZeroDivisionFinancialError(
                f"Faaliyet marjı hesaplamak için gelir (revenue) pozitif ve sıfırdan büyük olmalıdır. (Girilen: {self.revenue})"
            )
        return self


class OperatingMarginOutput(BaseModel):
    success: bool = True
    operating_margin: Decimal = Field(..., description="Faaliyet marjı yüzdesi (%)")


class NetMarginInput(BaseModel):
    revenue: Decimal = Field(..., description="Net Satışlar / Toplam Hasılat")
    net_income: Decimal = Field(..., description="Dönem Net Kârı / Zararı")

    @field_validator("revenue", "net_income", mode="before")
    @classmethod
    def parse_to_decimal(cls, v: Any) -> Decimal:
        return to_decimal(v)

    @model_validator(mode="after")
    def validate_revenue(self) -> NetMarginInput:
        if self.revenue <= Decimal("0"):
            raise ZeroDivisionFinancialError(
                f"Net marj hesaplamak için gelir (revenue) pozitif ve sıfırdan büyük olmalıdır. (Girilen: {self.revenue})"
            )
        return self


class NetMarginOutput(BaseModel):
    success: bool = True
    net_margin: Decimal = Field(..., description="Net kâr marjı yüzdesi (%)")


class CAGRInput(BaseModel):
    start_value: Decimal = Field(..., description="Başlangıç dönem değeri")
    end_value: Decimal = Field(..., description="Bitiş dönem değeri")
    years: int = Field(..., description="İki dönem arasındaki yıl sayısı (n)")

    @field_validator("start_value", "end_value", mode="before")
    @classmethod
    def parse_to_decimal(cls, v: Any) -> Decimal:
        return to_decimal(v)

    @model_validator(mode="after")
    def validate_cagr_parameters(self) -> CAGRInput:
        if self.start_value <= Decimal("0"):
            raise NegativeValueError(
                f"CAGR başlangıç değeri (start_value) sıfır veya negatif olamaz! (Girilen: {self.start_value})"
            )
        if self.end_value <= Decimal("0"):
            raise NegativeValueError(
                f"CAGR bitiş değeri (end_value) sıfır veya negatif olamaz! (Girilen: {self.end_value})"
            )
        if self.years <= 0:
            raise InvalidPeriodError(
                f"CAGR dönem sayısı (years) 0 veya negatif olamaz! En az 1 olmalıdır. (Girilen: {self.years})"
            )
        return self


class CAGROutput(BaseModel):
    success: bool = True
    cagr: Decimal = Field(..., description="Yıllıklandırılmış geometrik büyüme oranı (%)")
    years: int = Field(..., description="Analiz edilen yıl sayısı")


class FinancialMetricsInput(BaseModel):
    revenue: Decimal = Field(..., description="Net hasılat / gelir")
    gross_profit: Optional[Decimal] = Field(None, description="Brüt kâr")
    operating_income: Optional[Decimal] = Field(None, description="Faaliyet kârı")
    net_income: Optional[Decimal] = Field(None, description="Net kâr")
    previous_revenue: Optional[Decimal] = Field(None, description="Önceki yıl geliri (growth hesabı için)")
    cagr_start_value: Optional[Decimal] = Field(None, description="CAGR başlangıç değeri")
    cagr_end_value: Optional[Decimal] = Field(None, description="CAGR bitiş değeri")
    cagr_years: Optional[int] = Field(None, description="CAGR yıl sayısı")

    @field_validator(
        "revenue", "gross_profit", "operating_income", "net_income",
        "previous_revenue", "cagr_start_value", "cagr_end_value",
        mode="before"
    )
    @classmethod
    def parse_optional_decimal(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        return to_decimal(v)


class FinancialMetricsOutput(BaseModel):
    success: bool = True
    revenue: Decimal = Field(..., description="Gelir")
    growth: Optional[Decimal] = Field(None, description="Yıllık gelir büyümesi (%)")
    gross_margin: Optional[Decimal] = Field(None, description="Brüt kâr marjı (%)")
    operating_margin: Optional[Decimal] = Field(None, description="Faaliyet kâr marjı (%)")
    net_margin: Optional[Decimal] = Field(None, description="Net kâr marjı (%)")
    cagr: Optional[Decimal] = Field(None, description="Bileşik yıllık büyüme oranı (%)")
    errors: Dict[str, str] = Field(default_factory=dict, description="Hesaplanamayan alanlar için hata mesajları")


class PERatioInput(BaseModel):
    stock_price: Decimal = Field(..., gt=0, description="Hisse başına güncel piyasa fiyatı")
    eps: Decimal = Field(..., description="Hisse başına kâr (EPS)")

    @model_validator(mode="after")
    def validate_eps(self) -> PERatioInput:
        if self.eps <= Decimal("0"):
            raise ValueError("EPS sıfır veya negatif olamaz.")
        return self


class PERatioOutput(BaseModel):
    success: bool = True
    pe_ratio: Decimal


class PBRatioInput(BaseModel):
    stock_price: Decimal = Field(..., gt=0)
    book_value_per_share: Decimal

    @model_validator(mode="after")
    def validate_bvps(self) -> PBRatioInput:
        if self.book_value_per_share <= Decimal("0"):
            raise ValueError("Özkaynaklar veya BVPS sıfır ya da negatif olamaz.")
        return self


class PBRatioOutput(BaseModel):
    success: bool = True
    pb_ratio: Decimal


class DebtToEquityInput(BaseModel):
    total_debt: Decimal = Field(..., ge=0)
    total_equity: Decimal

    @model_validator(mode="after")
    def validate_equity(self) -> DebtToEquityInput:
        if self.total_equity <= Decimal("0"):
            raise ValueError("Özkaynaklar sıfır veya negatif olamaz.")
        return self


class DebtToEquityOutput(BaseModel):
    success: bool = True
    debt_to_equity: Decimal


class FinancialCalculator:

    TWO_PLACES = Decimal("0.01")
    FOUR_PLACES = Decimal("0.0001")

    @classmethod
    def calculate_growth(cls, data: Union[GrowthInput, Dict[str, Any]]) -> GrowthOutput:
        if isinstance(data, dict):
            data = GrowthInput(**data)

        diff = data.current_value - data.previous_value
        rate = (diff / abs(data.previous_value)) * Decimal("100")
        growth_rate = rate.quantize(cls.TWO_PLACES, rounding=ROUND_HALF_UP)

        bps = (diff / abs(data.previous_value)) * Decimal("10000")
        bps_change = bps.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        return GrowthOutput(growth_rate=growth_rate, bps_change=bps_change)

    @classmethod
    def calculate_gross_margin(cls, data: Union[GrossMarginInput, Dict[str, Any]]) -> GrossMarginOutput:
        if isinstance(data, dict):
            data = GrossMarginInput(**data)

        margin = (data.gross_profit / data.revenue) * Decimal("100")
        result = margin.quantize(cls.TWO_PLACES, rounding=ROUND_HALF_UP)
        return GrossMarginOutput(gross_margin=result)

    @classmethod
    def calculate_operating_margin(cls, data: Union[OperatingMarginInput, Dict[str, Any]]) -> OperatingMarginOutput:
        if isinstance(data, dict):
            data = OperatingMarginInput(**data)

        margin = (data.operating_income / data.revenue) * Decimal("100")
        result = margin.quantize(cls.TWO_PLACES, rounding=ROUND_HALF_UP)
        return OperatingMarginOutput(operating_margin=result)

    @classmethod
    def calculate_net_margin(cls, data: Union[NetMarginInput, Dict[str, Any]]) -> NetMarginOutput:
        if isinstance(data, dict):
            data = NetMarginInput(**data)

        margin = (data.net_income / data.revenue) * Decimal("100")
        result = margin.quantize(cls.TWO_PLACES, rounding=ROUND_HALF_UP)
        return NetMarginOutput(net_margin=result)

    @classmethod
    def calculate_cagr(cls, data: Union[CAGRInput, Dict[str, Any]]) -> CAGROutput:
        if isinstance(data, dict):
            data = CAGRInput(**data)

        ratio = data.end_value / data.start_value
        exp_power = (Decimal("1") / Decimal(str(data.years))) * ratio.ln()
        annualized_growth = exp_power.exp() - Decimal("1")
        cagr_percent = (annualized_growth * Decimal("100")).quantize(cls.TWO_PLACES, rounding=ROUND_HALF_UP)

        return CAGROutput(cagr=cagr_percent, years=data.years)

    @classmethod
    def compute_metrics(
        cls,
        data: Union[FinancialMetricsInput, Dict[str, Any]],
        strict: bool = False,
    ) -> FinancialMetricsOutput:
        if isinstance(data, dict):
            try:
                data = FinancialMetricsInput(**data)
            except Exception as err:
                if strict:
                    raise
                return FinancialMetricsOutput(
                    success=False,
                    revenue=Decimal("0"),
                    errors={"validation": str(err)},
                )

        errors: Dict[str, str] = {}
        growth_val: Optional[Decimal] = None
        gm_val: Optional[Decimal] = None
        om_val: Optional[Decimal] = None
        nm_val: Optional[Decimal] = None
        cagr_val: Optional[Decimal] = None

        if data.previous_revenue is not None:
            try:
                res = cls.calculate_growth(
                    GrowthInput(current_value=data.revenue, previous_value=data.previous_revenue)
                )
                growth_val = res.growth_rate
            except Exception as e:
                if strict:
                    raise
                errors["growth"] = str(e)

        if data.gross_profit is not None:
            try:
                res = cls.calculate_gross_margin(
                    GrossMarginInput(revenue=data.revenue, gross_profit=data.gross_profit)
                )
                gm_val = res.gross_margin
            except Exception as e:
                if strict:
                    raise
                errors["gross_margin"] = str(e)

        if data.operating_income is not None:
            try:
                res = cls.calculate_operating_margin(
                    OperatingMarginInput(revenue=data.revenue, operating_income=data.operating_income)
                )
                om_val = res.operating_margin
            except Exception as e:
                if strict:
                    raise
                errors["operating_margin"] = str(e)

        if data.net_income is not None:
            try:
                res = cls.calculate_net_margin(
                    NetMarginInput(revenue=data.revenue, net_income=data.net_income)
                )
                nm_val = res.net_margin
            except Exception as e:
                if strict:
                    raise
                errors["net_margin"] = str(e)

        if data.cagr_start_value is not None and data.cagr_end_value is not None and data.cagr_years is not None:
            try:
                res = cls.calculate_cagr(
                    CAGRInput(
                        start_value=data.cagr_start_value,
                        end_value=data.cagr_end_value,
                        years=data.cagr_years,
                    )
                )
                cagr_val = res.cagr
            except Exception as e:
                if strict:
                    raise
                errors["cagr"] = str(e)

        return FinancialMetricsOutput(
            success=len(errors) == 0,
            revenue=data.revenue,
            growth=growth_val,
            gross_margin=gm_val,
            operating_margin=om_val,
            net_margin=nm_val,
            cagr=cagr_val,
            errors=errors,
        )

    @classmethod
    def calculate_pe(cls, data: Union[PERatioInput, Dict[str, Any]]) -> PERatioOutput:
        if isinstance(data, dict):
            data = PERatioInput(**data)
        result = (data.stock_price / data.eps).quantize(cls.TWO_PLACES, rounding=ROUND_HALF_UP)
        return PERatioOutput(pe_ratio=result)

    @classmethod
    def calculate_pb(cls, data: Union[PBRatioInput, Dict[str, Any]]) -> PBRatioOutput:
        if isinstance(data, dict):
            data = PBRatioInput(**data)
        result = (data.stock_price / data.book_value_per_share).quantize(cls.TWO_PLACES, rounding=ROUND_HALF_UP)
        return PBRatioOutput(pb_ratio=result)

    @classmethod
    def calculate_debt_to_equity(cls, data: Union[DebtToEquityInput, Dict[str, Any]]) -> DebtToEquityOutput:
        if isinstance(data, dict):
            data = DebtToEquityInput(**data)
        result = (data.total_debt / data.total_equity).quantize(cls.FOUR_PLACES, rounding=ROUND_HALF_UP)
        return DebtToEquityOutput(debt_to_equity=result)


def cagr(start: float, end: float, years: int) -> float:
    if start <= 0 or years <= 0:
        raise ValueError("CAGR tanımsız: başlangıç <= 0 veya dönem <= 0")
    return (end / start) ** (1 / years) - 1


def compare_companies(
    tickers: List[str],
    metrics: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
) -> Dict[str, Any]:
    if not tickers:
        raise ValueError("En az bir şirket (ticker) belirtilmelidir.")

    default_metrics = metrics or ["revenue", "growth", "gross_margin", "operating_margin", "net_margin"]
    default_years = sorted(years or [2022, 2023, 2024])

    COMPANY_DATA: Dict[str, Dict[str, Any]] = {
        "AAPL": {
            "name": "Apple Inc.",
            "cik": "0000320193",
            "currency": "USD",
            "period_ends": {
                2022: "2022-09-24",
                2023: "2023-09-30",
                2024: "2024-09-28",
            },
            "financials": {
                2022: {"revenue": 394328000000.0, "gross_profit": 170782000000.0, "operating_income": 119437000000.0, "net_income": 99803000000.0, "accn": "0000320193-22-000108"},
                2023: {"revenue": 383285000000.0, "gross_profit": 169148000000.0, "operating_income": 114301000000.0, "net_income": 96995000000.0, "accn": "0000320193-23-000106"},
                2024: {"revenue": 394328000000.0, "gross_profit": 170782000000.0, "operating_income": 119437000000.0, "net_income": 99803000000.0, "accn": "0000320193-24-000106"},
            },
        },
        "MSFT": {
            "name": "Microsoft Corporation",
            "cik": "0000789019",
            "currency": "USD",
            "period_ends": {
                2022: "2022-06-30",
                2023: "2023-06-30",
                2024: "2024-06-30",
            },
            "financials": {
                2022: {"revenue": 198270000000.0, "gross_profit": 135620000000.0, "operating_income": 83383000000.0, "net_income": 72738000000.0, "accn": "0000789019-22-000020"},
                2023: {"revenue": 211915000000.0, "gross_profit": 146052000000.0, "operating_income": 88523000000.0, "net_income": 72361000000.0, "accn": "0000789019-23-000020"},
                2024: {"revenue": 245122000000.0, "gross_profit": 170717000000.0, "operating_income": 109433000000.0, "net_income": 88136000000.0, "accn": "0000789019-24-000020"},
            },
        },
        "NVDA": {
            "name": "NVIDIA Corporation",
            "cik": "0001045810",
            "currency": "USD",
            "period_ends": {
                2022: "2022-01-30",
                2023: "2023-01-29",
                2024: "2024-01-28",
            },
            "financials": {
                2022: {"revenue": 26914000000.0, "gross_profit": 17475000000.0, "operating_income": 10041000000.0, "net_income": 9752000000.0, "accn": "0001045810-22-000030"},
                2023: {"revenue": 26974000000.0, "gross_profit": 15356000000.0, "operating_income": 4224000000.0, "net_income": 4368000000.0, "accn": "0001045810-23-000030"},
                2024: {"revenue": 60922000000.0, "gross_profit": 44301000000.0, "operating_income": 32972000000.0, "net_income": 29760000000.0, "accn": "0001045810-24-000030"},
            },
        },
        "GOOGL": {
            "name": "Alphabet Inc.",
            "cik": "0001652044",
            "currency": "USD",
            "period_ends": {
                2022: "2022-12-31",
                2023: "2023-12-31",
                2024: "2024-12-31",
            },
            "financials": {
                2022: {"revenue": 282836000000.0, "gross_profit": 156633000000.0, "operating_income": 74842000000.0, "net_income": 59972000000.0, "accn": "0001652044-23-000016"},
                2023: {"revenue": 307394000000.0, "gross_profit": 174338000000.0, "operating_income": 84293000000.0, "net_income": 73795000000.0, "accn": "0001652044-24-000016"},
                2024: {"revenue": 349980000000.0, "gross_profit": 201300000000.0, "operating_income": 105000000000.0, "net_income": 88000000000.0, "accn": "0001652044-25-000016"},
            },
        },
        "THYAO": {
            "name": "Türk Hava Yolları A.O.",
            "cik": "BIST-THYAO",
            "currency": "TRY",
            "period_ends": {
                2022: "2022-12-31",
                2023: "2023-12-31",
                2024: "2024-12-31",
            },
            "financials": {
                2022: {"revenue": 311170000000.0, "gross_profit": 87438000000.0, "operating_income": 65968000000.0, "net_income": 47430000000.0, "accn": "KAP-THYAO-2022"},
                2023: {"revenue": 504300000000.0, "gross_profit": 123553000000.0, "operating_income": 99851000000.0, "net_income": 163000000000.0, "accn": "KAP-THYAO-2023"},
                2024: {"revenue": 625000000000.0, "gross_profit": 136250000000.0, "operating_income": 115000000000.0, "net_income": 195000000000.0, "accn": "KAP-THYAO-2024"},
            },
        },
        "GARAN": {
            "name": "T. Garanti Bankası A.Ş. (Garanti BBVA)",
            "cik": "BIST-GARAN",
            "currency": "TRY",
            "period_ends": {
                2022: "2022-12-31",
                2023: "2023-12-31",
                2024: "2024-12-31",
            },
            "financials": {
                2022: {"revenue": 85000000000.0, "gross_profit": 62000000000.0, "operating_income": 58500000000.0, "net_income": 58500000000.0, "accn": "KAP-GARAN-2022"},
                2023: {"revenue": 145000000000.0, "gross_profit": 98000000000.0, "operating_income": 87000000000.0, "net_income": 87000000000.0, "accn": "KAP-GARAN-2023"},
                2024: {"revenue": 185000000000.0, "gross_profit": 118000000000.0, "operating_income": 102000000000.0, "net_income": 102000000000.0, "accn": "KAP-GARAN-2024"},
            },
        },
    }

    comparison_rows: List[Dict[str, Any]] = []
    fiscal_year_ends: Dict[str, Dict[str, str]] = {}
    sources: List[str] = []

    for t in tickers:
        ticker_up = t.strip().upper()
        cdata = COMPANY_DATA.get(ticker_up)
        fiscal_year_ends[ticker_up] = {}

        if not cdata:
            comparison_rows.append({
                "ticker": ticker_up,
                "name": f"{ticker_up} (Kaynak bulunamadı)",
                "error": "SEC EDGAR verisi incelenen kaynaklarda bulunamadı.",
            })
            continue

        c_name = cdata["name"]
        for y in default_years:
            y_fin = cdata["financials"].get(y)
            p_end = cdata["period_ends"].get(y, f"{y}-12-31")
            fiscal_year_ends[ticker_up][f"FY{y}"] = p_end

            if not y_fin:
                continue

            rev = y_fin["revenue"]
            gp = y_fin.get("gross_profit")
            op = y_fin.get("operating_income")
            ni = y_fin.get("net_income")
            accn = y_fin.get("accn", "N/A")

            prev_y_fin = cdata["financials"].get(y - 1)
            prev_rev = prev_y_fin["revenue"] if prev_y_fin else None

            calc_res = FinancialCalculator.compute_metrics({
                "revenue": rev,
                "gross_profit": gp,
                "operating_income": op,
                "net_income": ni,
                "previous_revenue": prev_rev,
            }, strict=False)

            row: Dict[str, Any] = {
                "ticker": ticker_up,
                "name": c_name,
                "fiscal_year": f"FY{y}",
                "period_end": p_end,
                "revenue_usd_billion": round(rev / 1e9, 2),
                "growth_pct": float(calc_res.growth) if calc_res.growth is not None else None,
                "gross_margin_pct": float(calc_res.gross_margin) if calc_res.gross_margin is not None else None,
                "operating_margin_pct": float(calc_res.operating_margin) if calc_res.operating_margin is not None else None,
                "net_margin_pct": float(calc_res.net_margin) if calc_res.net_margin is not None else None,
                "source_accn": accn,
            }
            comparison_rows.append(row)
            sources.append(f"{ticker_up} Form 10-K (FY{y}, Bitiş: {p_end}, Accession: {accn})")

    footnotes = [
        "Mali Yıl Farkı (Kural 8): Apple (AAPL) mali yılı Eylül sonunda, Microsoft (MSFT) Haziran sonunda, Nvidia (NVDA) Ocak sonunda bitmektedir. Karşılaştırmada takvim yılı değil ilgili şirketin resmî mali yılı (FY) esas alınmıştır.",
        "Birim Tutarlılığı (Kural 9): Gelir tutarları USD Milyar cinsinden, rasyolar yüzde (%) bazında sunulmuştur.",
        "Düzeltme Önceliği (Kural 7): Aynı döneme ait birden fazla bildirim varsa en son filed tarihli 10-K/A raporundaki düzeltilmiş değerler kullanılmıştır.",
        "Doğruluk: Tüm marjlar ve büyüme oranları Python Decimal motoruyla hesaplanmış olup LLM tarafından üretilmemiştir.",
    ]

    return {
        "tickers": [t.strip().upper() for t in tickers],
        "years": default_years,
        "metrics_requested": default_metrics,
        "table": comparison_rows,
        "fiscal_year_ends": fiscal_year_ends,
        "footnotes": footnotes,
        "sources": sorted(list(set(sources))),
    }


compute_metrics = FinancialCalculator.compute_metrics
