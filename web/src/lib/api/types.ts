import type { components } from "./types.gen";

type S = components["schemas"];
export type Product = S["ProductView"];
export type Offer = S["OfferView"];
export type Page = S["Page"];
export type RecommendResponse = S["RecommendResponse"];
export type Result = S["Result"];
export type CardRequest = S["CardRequest"];
export type CheckingRequest = S["CheckingRequest"];
export type SavingsRequest = S["SavingsRequest"];
export type RecommendRequest = CardRequest | CheckingRequest | SavingsRequest;
export type CompareResponse = S["CompareResponse"];
export type HistoryEntry = S["HistoryEntry"];
export type SourcesResponse = S["SourcesResponse"];
export type ProductType = Product["product_type"];
export type PublicOffers = S["PublicOffersResponse"];
export type RankedOffer = S["RankedOffer"];
export type UnrankedOffer = S["UnrankedOffer"];
export type OfferSort = PublicOffers["sort"];
export type OfferGroup = NonNullable<PublicOffers["group"]>;
// Offer tracker (DESIGN §27)
export type Campaign = S["CampaignView"];
export type CampaignDetail = S["CampaignDetail"];
export type CampaignPage = S["CampaignPage"];
export type CampaignTerms = S["Terms"];
export type CampaignMoment = S["Moment"];
export type ApplicationRule = S["RuleView"];
export type PointValue = S["PointValue"];
/** Every profile answer is optional (server defaults apply). */
export type HeldCard = Omit<S["HeldCard"], "authorized_user" | "product_change"> & Partial<Pick<S["HeldCard"], "authorized_user" | "product_change">>;
export type MatchProfile = Partial<Omit<S["MatchProfile"], "cards">> & { cards?: HeldCard[] };
export type MatchRequest = S["MatchRequest"];
export type MatchResponse = S["MatchResponse"];
export type Assessment = S["Assessment"];
export type MatchFinding = S["FindingView"];
export type Judgement = S["Judgement"];
export type CardSummary = S["CardSummary"];
