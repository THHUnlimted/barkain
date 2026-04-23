import Foundation
import Testing
@testable import Barkain

// MARK: - PortalMembershipPreferencesTests (Step 3g-B)

@Suite("PortalMembershipPreferences round-trips + isolation")
struct PortalMembershipPreferencesTests {

    /// Each test gets its own throwaway UserDefaults suite so persisted
    /// values don't leak across tests or across the actual app preferences.
    private static func makeIsolatedDefaults() -> UserDefaults {
        let suiteName = "barkain.tests.portalmembership.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return defaults
    }

    @Test("Empty store returns empty dict and isMember==false for all known portals")
    func test_emptyStore_isCleanInitial() {
        let prefs = PortalMembershipPreferences(defaults: Self.makeIsolatedDefaults())
        #expect(prefs.current() == [:])
        for portal in PortalMembershipPreferences.knownPortals {
            #expect(prefs.isMember(portal) == false)
        }
    }

    @Test("setMember persists and round-trips through current()")
    func test_setMember_persists() {
        let defaults = Self.makeIsolatedDefaults()
        let prefs = PortalMembershipPreferences(defaults: defaults)

        prefs.setMember("rakuten", isMember: true)
        prefs.setMember("topcashback", isMember: false)

        // Re-read from a fresh instance backed by the same defaults
        // simulates a relaunch — values must survive.
        let reread = PortalMembershipPreferences(defaults: defaults)
        #expect(reread.current() == ["rakuten": true, "topcashback": false])
        #expect(reread.isMember("rakuten") == true)
        #expect(reread.isMember("topcashback") == false)
        // BeFrugal was never set; reads as false.
        #expect(reread.isMember("befrugal") == false)
    }

    @Test("Toggling one portal preserves the other portals' state")
    func test_setMember_preservesOthers() {
        let prefs = PortalMembershipPreferences(defaults: Self.makeIsolatedDefaults())
        prefs.setMember("rakuten", isMember: true)
        prefs.setMember("befrugal", isMember: true)

        prefs.setMember("rakuten", isMember: false)

        #expect(prefs.isMember("rakuten") == false)
        #expect(prefs.isMember("befrugal") == true)
    }

    @Test("clear() empties the store")
    func test_clear_emptiesStore() {
        let prefs = PortalMembershipPreferences(defaults: Self.makeIsolatedDefaults())
        prefs.setMember("rakuten", isMember: true)
        prefs.setMember("topcashback", isMember: true)

        prefs.clear()

        #expect(prefs.current() == [:])
        #expect(prefs.isMember("rakuten") == false)
    }

    @Test("knownPortals + displayNames cover the three active portals")
    func test_knownPortals_haveDisplayNames() {
        for portal in PortalMembershipPreferences.knownPortals {
            #expect(PortalMembershipPreferences.displayNames[portal] != nil)
        }
        #expect(PortalMembershipPreferences.knownPortals.count == 3)
    }
}
