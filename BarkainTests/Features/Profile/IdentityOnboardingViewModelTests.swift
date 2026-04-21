import XCTest
@testable import Barkain

@MainActor
final class IdentityOnboardingViewModelTests: XCTestCase {

    // MARK: - Properties

    private var mockClient: MockAPIClient!
    private var viewModel: IdentityOnboardingViewModel!

    // MARK: - Setup

    override func setUp() {
        super.setUp()
        mockClient = MockAPIClient()
        viewModel = IdentityOnboardingViewModel(apiClient: mockClient)
    }

    override func tearDown() {
        viewModel = nil
        mockClient = nil
        super.tearDown()
    }

    // MARK: - Tests

    func test_save_callsAPI_withCorrectFlags() async {
        // Given
        viewModel.request.isVeteran = true
        viewModel.request.isStudent = true
        viewModel.request.idMeVerified = true

        // When
        await viewModel.save()

        // Then
        XCTAssertEqual(mockClient.updateIdentityProfileCallCount, 1)
        let last = mockClient.updateIdentityProfileLastRequest
        XCTAssertEqual(last?.isVeteran, true)
        XCTAssertEqual(last?.isStudent, true)
        XCTAssertEqual(last?.idMeVerified, true)
        XCTAssertEqual(last?.isMilitary, false)
        XCTAssertEqual(last?.isGovernment, false)
        XCTAssertTrue(viewModel.saved)
        XCTAssertNil(viewModel.error)
        XCTAssertFalse(viewModel.isSaving)
    }

    func test_skip_callsAPI_withAllFalse() async {
        // Given — no toggles touched, all defaults are false

        // When
        await viewModel.skip()

        // Then — skip posts the default all-false request
        XCTAssertEqual(mockClient.updateIdentityProfileCallCount, 1)
        let last = mockClient.updateIdentityProfileLastRequest
        XCTAssertNotNil(last)
        XCTAssertEqual(last?.isMilitary, false)
        XCTAssertEqual(last?.isVeteran, false)
        XCTAssertEqual(last?.isStudent, false)
        XCTAssertEqual(last?.isTeacher, false)
        XCTAssertEqual(last?.isFirstResponder, false)
        XCTAssertEqual(last?.isNurse, false)
        XCTAssertEqual(last?.isHealthcareWorker, false)
        XCTAssertEqual(last?.isSenior, false)
        XCTAssertEqual(last?.isGovernment, false)
        XCTAssertEqual(last?.isYoungAdult, false)
        XCTAssertEqual(last?.isAaaMember, false)
        XCTAssertEqual(last?.isAarpMember, false)
        XCTAssertEqual(last?.isCostcoMember, false)
        XCTAssertEqual(last?.isPrimeMember, false)
        XCTAssertEqual(last?.isSamsMember, false)
        XCTAssertEqual(last?.idMeVerified, false)
        XCTAssertEqual(last?.sheerIdVerified, false)
        XCTAssertTrue(viewModel.saved)
    }

    func test_saveFailure_setsError_andSavedRemainsFalse() async {
        // Given
        mockClient.updateIdentityProfileResult = .failure(.server("500 internal"))
        viewModel.request.isVeteran = true

        // When
        await viewModel.save()

        // Then
        XCTAssertFalse(viewModel.saved)
        XCTAssertNotNil(viewModel.error)
        if case .server(let message) = viewModel.error {
            XCTAssertEqual(message, "500 internal")
        } else {
            XCTFail("Expected .server error, got \(String(describing: viewModel.error))")
        }
        XCTAssertFalse(viewModel.isSaving)
    }

    func test_editFlow_preservesInitialProfile() async {
        // Given — a pre-existing veteran profile
        let initial = TestFixtures.veteranIdentityProfile
        viewModel = IdentityOnboardingViewModel(apiClient: mockClient, initial: initial)

        // Then — draft mirrors the initial profile
        XCTAssertTrue(viewModel.request.isVeteran)
        XCTAssertTrue(viewModel.request.idMeVerified)
        XCTAssertFalse(viewModel.request.isStudent)
    }

    func test_identityProfile_decodes_isYoungAdult() throws {
        // Benefits Expansion: ensure convertFromSnakeCase maps is_young_adult → isYoungAdult.
        let json = """
        {
            "user_id": "u",
            "is_military": false, "is_veteran": false, "is_student": false,
            "is_teacher": false, "is_first_responder": false, "is_nurse": false,
            "is_healthcare_worker": false, "is_senior": false, "is_government": false,
            "is_young_adult": true,
            "is_aaa_member": false, "is_aarp_member": false,
            "is_costco_member": false, "is_prime_member": false, "is_sams_member": false,
            "id_me_verified": false, "sheer_id_verified": false,
            "created_at": "2026-04-21T00:00:00Z",
            "updated_at": "2026-04-21T00:00:00Z"
        }
        """.data(using: .utf8)!

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601

        let profile = try decoder.decode(IdentityProfile.self, from: json)
        XCTAssertTrue(profile.isYoungAdult)
        XCTAssertFalse(profile.isStudent)
    }
}
