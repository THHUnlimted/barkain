import Foundation

// MARK: - IdentityProfile
// Snake-case keys from the backend are mapped via JSONDecoder's
// .convertFromSnakeCase strategy (see APIClient.swift:47).

nonisolated struct IdentityProfile: Codable, Equatable, Sendable {
    let userId: String
    var isMilitary: Bool
    var isVeteran: Bool
    var isStudent: Bool
    var isTeacher: Bool
    var isFirstResponder: Bool
    var isNurse: Bool
    var isHealthcareWorker: Bool
    var isSenior: Bool
    var isGovernment: Bool
    var isAaaMember: Bool
    var isAarpMember: Bool
    var isCostcoMember: Bool
    var isPrimeMember: Bool
    var isSamsMember: Bool
    var idMeVerified: Bool
    var sheerIdVerified: Bool
    let createdAt: Date
    let updatedAt: Date
}

// MARK: - IdentityProfileRequest

nonisolated struct IdentityProfileRequest: Codable, Equatable, Sendable {
    var isMilitary: Bool = false
    var isVeteran: Bool = false
    var isStudent: Bool = false
    var isTeacher: Bool = false
    var isFirstResponder: Bool = false
    var isNurse: Bool = false
    var isHealthcareWorker: Bool = false
    var isSenior: Bool = false
    var isGovernment: Bool = false
    var isAaaMember: Bool = false
    var isAarpMember: Bool = false
    var isCostcoMember: Bool = false
    var isPrimeMember: Bool = false
    var isSamsMember: Bool = false
    var idMeVerified: Bool = false
    var sheerIdVerified: Bool = false

    /// Build a request from an existing profile (for the "Edit Profile" flow).
    init(from profile: IdentityProfile) {
        self.isMilitary = profile.isMilitary
        self.isVeteran = profile.isVeteran
        self.isStudent = profile.isStudent
        self.isTeacher = profile.isTeacher
        self.isFirstResponder = profile.isFirstResponder
        self.isNurse = profile.isNurse
        self.isHealthcareWorker = profile.isHealthcareWorker
        self.isSenior = profile.isSenior
        self.isGovernment = profile.isGovernment
        self.isAaaMember = profile.isAaaMember
        self.isAarpMember = profile.isAarpMember
        self.isCostcoMember = profile.isCostcoMember
        self.isPrimeMember = profile.isPrimeMember
        self.isSamsMember = profile.isSamsMember
        self.idMeVerified = profile.idMeVerified
        self.sheerIdVerified = profile.sheerIdVerified
    }

    init() {}
}

// MARK: - EligibleDiscount

nonisolated struct EligibleDiscount: Codable, Equatable, Sendable, Identifiable {
    var id: UUID { programId }
    let programId: UUID
    let retailerId: String
    let retailerName: String
    let programName: String
    let eligibilityType: String?
    let discountType: String
    let discountValue: Double?
    let discountMaxValue: Double?
    let discountDetails: String?
    let verificationMethod: String?
    let verificationUrl: String?
    let url: String?
    let estimatedSavings: Double?
}

// MARK: - IdentityDiscountsResponse

nonisolated struct IdentityDiscountsResponse: Codable, Equatable, Sendable {
    let eligibleDiscounts: [EligibleDiscount]
    let identityGroupsActive: [String]
}
