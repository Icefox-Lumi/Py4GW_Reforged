from Py4GWCoreLib import Map
from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
from Py4GWCoreLib.GlobalCache.SharedMemory import AccountStruct, HeroAIOptionStruct
from Py4GWCoreLib.py4gwcorelib_src.Console import ConsoleLog


class PartyCache():
    def __init__(self):
        super().__init__()
        
        self.accounts : dict[int, AccountStruct] = {}
        self.options : dict[int, HeroAIOptionStruct] = {}
        
        # Last valid options per account email. Stored as DETACHED copies because
        # shared-memory structs are live views: when the C++ writer moves an
        # account to a different slot index, the bytes behind a cached view can
        # be repurposed by another account. These copies are the recovery source
        # when options temporarily disappear from shared memory.
        self.last_valid_options : dict[str, HeroAIOptionStruct] = {}
        
        # Emails that already logged the "no options" fallback this session, so a
        # flapping slot cannot spam the console every frame.
        self._missing_options_logged : set[str] = set()
        
        self.party_id = 0
        
    def __iter__(self):
        """ Iterate over all accounts in the party cache. """
        for acc in self.accounts.values():
            yield acc
    
    def get_by_player_id(self, player_id: int) -> AccountStruct | None:
        """ Get account data by player ID. """
        return self.accounts.get(player_id, None)
    
    def get_by_party_pos(self, party_pos: int) -> AccountStruct | None:
        """ Get account data by party position. """
        for acc in self.accounts.values():
            if acc.AgentPartyData.PartyPosition == party_pos:
                return acc
        
        return None
    
    def reset(self):
        """ Reset the party cache. """
        self.accounts.clear()
        self.options.clear()
        self.party_id = 0
        # last_valid_options survives resets on purpose: it is the recovery data
        # that keeps accounts enabled across temporary shared-memory gaps.
        
    def update(self):
        """ Update the party cache from shared memory. """
        from .utils import SameMapOrPartyAsAccount, detached_hero_ai_options
        from Py4GWCoreLib.Party import Party
        if not Party.IsPartyLoaded():
            self.reset()
            return
        
        
        self.party_id = GLOBAL_CACHE.Party.GetPartyID()
        
        shmem_accounts = GLOBAL_CACHE.ShMem.GetAllActiveSlotsData()
        
        for acc in shmem_accounts:
            if acc.IsSlotActive and SameMapOrPartyAsAccount(acc):
                agent_id = acc.AgentData.AgentID
                email = acc.AccountEmail
                
                self.accounts[agent_id] = acc
                
                options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(email)
                
                if options is None:
                    # Temporary shared-memory gap (slot bounce, region recreation,
                    # heartbeat flicker). Reuse the last valid options so the
                    # account keeps Following/Combat/Targeting/Looting/skills as
                    # they were instead of being downgraded to an all-zero struct,
                    # which silently disables every HeroAI subsystem.
                    options = self.last_valid_options.get(email)
                    if options is None:
                        if email not in self._missing_options_logged:
                            self._missing_options_logged.add(email)
                            ConsoleLog("PartyCache", f"Account {email} has no HeroAI options in shared memory, using enabled defaults.")
                        options = HeroAIOptionStruct()
                        options.reset()
                    self.options[agent_id] = options
                    continue
                
                self._missing_options_logged.discard(email)
                options_copy = detached_hero_ai_options(options)
                self.last_valid_options[email] = options_copy
                self.options[agent_id] = options_copy
