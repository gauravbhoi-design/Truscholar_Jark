// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/token/ERC1155/ERC1155Upgradeable.sol";
import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/token/ERC1155/extensions/ERC1155SupplyUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";

/**
 * @title SkillBadge
 * @notice ERC1155 multi-token contract for issuing verifiable skill badges to engineers.
 *         Each token ID represents a skill category. Badges are soulbound (non-transferable)
 *         by default to prevent credential fraud.
 */
contract SkillBadge is
    Initializable,
    ERC1155Upgradeable,
    AccessControlUpgradeable,
    ERC1155SupplyUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable
{
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    bytes32 public constant URI_SETTER_ROLE = keccak256("URI_SETTER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");

    struct SkillType {
        string name;
        string category;
        uint64 createdAt;
        bool active;
    }

    struct BadgeMetadata {
        uint64 issuedAt;
        uint64 expiresAt;
        bytes32 evidenceHash; // hash of evidence/proof for the skill
        uint8 level;          // 1-5 proficiency level
    }

    // Skill type definitions: tokenId => SkillType
    mapping(uint256 => SkillType) public skillTypes;

    // Badge metadata: tokenId => engineer => BadgeMetadata
    mapping(uint256 => mapping(address => BadgeMetadata)) public badgeMetadata;

    // Whether badges are soulbound (non-transferable)
    bool public soulbound;

    // Next token ID
    uint256 private _nextTokenId;

    // Contract name for marketplace display
    string public name;
    string public symbol;

    event SkillTypeCreated(uint256 indexed tokenId, string name, string category);
    event BadgeIssued(
        uint256 indexed tokenId,
        address indexed engineer,
        uint8 level,
        bytes32 evidenceHash
    );
    event BadgeBatchIssued(
        uint256 indexed tokenId,
        address[] engineers,
        uint8[] levels
    );
    event SkillTypeDeactivated(uint256 indexed tokenId);
    event SoulboundToggled(bool enabled);

    error SkillTypeNotFound(uint256 tokenId);
    error SkillTypeInactive(uint256 tokenId);
    error InvalidLevel(uint8 level);
    error BadgeAlreadyIssued(uint256 tokenId, address engineer);
    error SoulboundTransferBlocked();
    error EmptyName();
    error ArrayLengthMismatch();

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function initialize(
        address admin,
        string memory uri_,
        string memory name_,
        string memory symbol_
    ) external initializer {
        __ERC1155_init(uri_);
        __AccessControl_init();
        __ERC1155Supply_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(MINTER_ROLE, admin);
        _grantRole(URI_SETTER_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);

        name = name_;
        symbol = symbol_;
        soulbound = true; // Soulbound by default
    }

    // ─── Skill Type Management ─────────────────────────────────────────

    /**
     * @notice Create a new skill type (e.g., "Kubernetes", "CI/CD", "Security")
     * @param skillName Name of the skill
     * @param category Category grouping (e.g., "Infrastructure", "Development")
     * @return tokenId The new skill type's token ID
     */
    function createSkillType(string calldata skillName, string calldata category)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
        returns (uint256 tokenId)
    {
        if (bytes(skillName).length == 0) revert EmptyName();

        tokenId = _nextTokenId++;
        skillTypes[tokenId] = SkillType({
            name: skillName,
            category: category,
            createdAt: uint64(block.timestamp),
            active: true
        });

        emit SkillTypeCreated(tokenId, skillName, category);
    }

    /**
     * @notice Deactivate a skill type (no new badges can be minted)
     */
    function deactivateSkillType(uint256 tokenId)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        if (skillTypes[tokenId].createdAt == 0) revert SkillTypeNotFound(tokenId);
        skillTypes[tokenId].active = false;
        emit SkillTypeDeactivated(tokenId);
    }

    // ─── Badge Issuance ────────────────────────────────────────────────

    /**
     * @notice Issue a skill badge to an engineer
     * @param engineer Recipient address
     * @param tokenId Skill type token ID
     * @param level Proficiency level (1-5)
     * @param expiresAt Expiry timestamp (0 = never)
     * @param evidenceHash Hash of supporting evidence
     */
    function issueBadge(
        address engineer,
        uint256 tokenId,
        uint8 level,
        uint64 expiresAt,
        bytes32 evidenceHash
    ) external onlyRole(MINTER_ROLE) whenNotPaused {
        _validateBadgeIssuance(engineer, tokenId, level);

        badgeMetadata[tokenId][engineer] = BadgeMetadata({
            issuedAt: uint64(block.timestamp),
            expiresAt: expiresAt,
            evidenceHash: evidenceHash,
            level: level
        });

        _mint(engineer, tokenId, 1, "");
        emit BadgeIssued(tokenId, engineer, level, evidenceHash);
    }

    /**
     * @notice Batch issue the same skill badge to multiple engineers
     * @param engineers Array of recipient addresses
     * @param tokenId Skill type token ID
     * @param levels Array of proficiency levels
     * @param expiresAt Shared expiry timestamp
     * @param evidenceHashes Array of evidence hashes
     */
    function batchIssueBadge(
        address[] calldata engineers,
        uint256 tokenId,
        uint8[] calldata levels,
        uint64 expiresAt,
        bytes32[] calldata evidenceHashes
    ) external onlyRole(MINTER_ROLE) whenNotPaused {
        uint256 len = engineers.length;
        if (len != levels.length || len != evidenceHashes.length) revert ArrayLengthMismatch();

        for (uint256 i; i < len; ) {
            _validateBadgeIssuance(engineers[i], tokenId, levels[i]);

            badgeMetadata[tokenId][engineers[i]] = BadgeMetadata({
                issuedAt: uint64(block.timestamp),
                expiresAt: expiresAt,
                evidenceHash: evidenceHashes[i],
                level: levels[i]
            });

            _mint(engineers[i], tokenId, 1, "");
            unchecked { ++i; }
        }

        emit BadgeBatchIssued(tokenId, engineers, levels);
    }

    // ─── Verification ──────────────────────────────────────────────────

    /**
     * @notice Check if an engineer holds a valid (non-expired) badge
     */
    function hasValidBadge(address engineer, uint256 tokenId)
        external
        view
        returns (bool valid, uint8 level, uint64 issuedAt, uint64 expiresAt)
    {
        if (balanceOf(engineer, tokenId) == 0) return (false, 0, 0, 0);

        BadgeMetadata storage meta = badgeMetadata[tokenId][engineer];
        bool notExpired = meta.expiresAt == 0 || meta.expiresAt > block.timestamp;

        return (notExpired, meta.level, meta.issuedAt, meta.expiresAt);
    }

    /**
     * @notice Get all badge details for an engineer across a set of skill types
     */
    function getEngineerBadges(address engineer, uint256[] calldata tokenIds)
        external
        view
        returns (BadgeMetadata[] memory badges, uint256[] memory balances)
    {
        uint256 len = tokenIds.length;
        badges = new BadgeMetadata[](len);
        balances = new uint256[](len);

        for (uint256 i; i < len; ) {
            badges[i] = badgeMetadata[tokenIds[i]][engineer];
            balances[i] = balanceOf(engineer, tokenIds[i]);
            unchecked { ++i; }
        }
    }

    // ─── Soulbound Logic ───────────────────────────────────────────────

    function toggleSoulbound(bool enabled) external onlyRole(DEFAULT_ADMIN_ROLE) {
        soulbound = enabled;
        emit SoulboundToggled(enabled);
    }

    function setURI(string memory newuri) external onlyRole(URI_SETTER_ROLE) {
        _setURI(newuri);
    }

    function pause() external onlyRole(PAUSER_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    function nextTokenId() external view returns (uint256) {
        return _nextTokenId;
    }

    // ─── Internal ──────────────────────────────────────────────────────

    function _validateBadgeIssuance(
        address engineer,
        uint256 tokenId,
        uint8 level
    ) internal view {
        if (skillTypes[tokenId].createdAt == 0) revert SkillTypeNotFound(tokenId);
        if (!skillTypes[tokenId].active) revert SkillTypeInactive(tokenId);
        if (level == 0 || level > 5) revert InvalidLevel(level);
        if (balanceOf(engineer, tokenId) > 0) revert BadgeAlreadyIssued(tokenId, engineer);
    }

    function _update(
        address from,
        address to,
        uint256[] memory ids,
        uint256[] memory values
    ) internal override(ERC1155Upgradeable, ERC1155SupplyUpgradeable) {
        // Block transfers if soulbound (allow mint and burn)
        if (soulbound && from != address(0) && to != address(0)) {
            revert SoulboundTransferBlocked();
        }
        super._update(from, to, ids, values);
    }

    function _authorizeUpgrade(address newImplementation)
        internal
        override
        onlyRole(DEFAULT_ADMIN_ROLE)
    {}

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC1155Upgradeable, AccessControlUpgradeable)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}
