// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";

/**
 * @title CredentialVerification
 * @notice On-chain hash verification for engineer credentials.
 *         Stores credential hashes and allows tamper-proof verification.
 *         Upgradeable via UUPS proxy pattern.
 */
contract CredentialVerification is
    Initializable,
    AccessControlUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable
{
    bytes32 public constant ISSUER_ROLE = keccak256("ISSUER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");

    struct Credential {
        bytes32 credentialHash;
        address issuer;
        uint64 issuedAt;
        uint64 expiresAt;
        bool revoked;
    }

    // credentialId => Credential
    mapping(bytes32 => Credential) private _credentials;

    // engineer address => list of credential IDs
    mapping(address => bytes32[]) private _engineerCredentials;

    // credentialHash => credentialId (reverse lookup)
    mapping(bytes32 => bytes32) private _hashToId;

    uint256 private _totalCredentials;

    event CredentialRegistered(
        bytes32 indexed credentialId,
        address indexed engineer,
        bytes32 credentialHash,
        address issuer,
        uint64 expiresAt
    );

    event CredentialRevoked(bytes32 indexed credentialId, address indexed revoker);

    event CredentialBatchRegistered(
        address indexed issuer,
        uint256 count,
        bytes32[] credentialIds
    );

    error CredentialAlreadyExists(bytes32 credentialId);
    error CredentialNotFound(bytes32 credentialId);
    error CredentialAlreadyRevoked(bytes32 credentialId);
    error InvalidExpiryDate();
    error EmptyBatch();
    error BatchTooLarge(uint256 size, uint256 max);
    error ZeroAddress();
    error EmptyHash();

    uint256 public constant MAX_BATCH_SIZE = 100;

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function initialize(address admin) external initializer {
        if (admin == address(0)) revert ZeroAddress();

        __AccessControl_init();
        __Pausable_init();
        __UUPSUpgradeable_init();

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ISSUER_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);
    }

    /**
     * @notice Register a single credential on-chain
     * @param engineer The engineer's wallet address
     * @param credentialHash Keccak256 hash of the credential data
     * @param expiresAt Unix timestamp when credential expires (0 = never)
     * @return credentialId The unique credential identifier
     */
    function registerCredential(
        address engineer,
        bytes32 credentialHash,
        uint64 expiresAt
    ) external onlyRole(ISSUER_ROLE) whenNotPaused returns (bytes32 credentialId) {
        if (engineer == address(0)) revert ZeroAddress();
        if (credentialHash == bytes32(0)) revert EmptyHash();
        if (expiresAt != 0 && expiresAt <= block.timestamp) revert InvalidExpiryDate();

        credentialId = keccak256(
            abi.encodePacked(engineer, credentialHash, block.timestamp, _totalCredentials)
        );

        if (_credentials[credentialId].issuedAt != 0) {
            revert CredentialAlreadyExists(credentialId);
        }

        _credentials[credentialId] = Credential({
            credentialHash: credentialHash,
            issuer: msg.sender,
            issuedAt: uint64(block.timestamp),
            expiresAt: expiresAt,
            revoked: false
        });

        _engineerCredentials[engineer].push(credentialId);
        _hashToId[credentialHash] = credentialId;
        _totalCredentials++;

        emit CredentialRegistered(credentialId, engineer, credentialHash, msg.sender, expiresAt);
    }

    /**
     * @notice Batch register credentials with gas optimization
     * @param engineers Array of engineer addresses
     * @param credentialHashes Array of credential hashes
     * @param expiresAts Array of expiry timestamps
     * @return credentialIds Array of generated credential IDs
     */
    function batchRegisterCredentials(
        address[] calldata engineers,
        bytes32[] calldata credentialHashes,
        uint64[] calldata expiresAts
    )
        external
        onlyRole(ISSUER_ROLE)
        whenNotPaused
        returns (bytes32[] memory credentialIds)
    {
        uint256 len = engineers.length;
        if (len == 0) revert EmptyBatch();
        if (len > MAX_BATCH_SIZE) revert BatchTooLarge(len, MAX_BATCH_SIZE);
        require(len == credentialHashes.length && len == expiresAts.length, "Array length mismatch");

        credentialIds = new bytes32[](len);
        uint256 total = _totalCredentials;

        for (uint256 i; i < len; ) {
            address engineer = engineers[i];
            bytes32 credHash = credentialHashes[i];
            uint64 expiresAt = expiresAts[i];

            if (engineer == address(0)) revert ZeroAddress();
            if (credHash == bytes32(0)) revert EmptyHash();

            bytes32 credId = keccak256(
                abi.encodePacked(engineer, credHash, block.timestamp, total)
            );

            _credentials[credId] = Credential({
                credentialHash: credHash,
                issuer: msg.sender,
                issuedAt: uint64(block.timestamp),
                expiresAt: expiresAt,
                revoked: false
            });

            _engineerCredentials[engineer].push(credId);
            _hashToId[credHash] = credId;
            credentialIds[i] = credId;
            total++;

            unchecked { ++i; }
        }

        _totalCredentials = total;
        emit CredentialBatchRegistered(msg.sender, len, credentialIds);
    }

    /**
     * @notice Verify a credential by its hash
     * @param credentialHash The hash to verify
     * @return valid Whether the credential is valid
     * @return issuer The credential issuer
     * @return issuedAt When the credential was issued
     * @return expiresAt When the credential expires
     */
    function verifyByHash(bytes32 credentialHash)
        external
        view
        returns (bool valid, address issuer, uint64 issuedAt, uint64 expiresAt)
    {
        bytes32 credId = _hashToId[credentialHash];
        if (credId == bytes32(0)) return (false, address(0), 0, 0);

        Credential storage cred = _credentials[credId];
        bool isValid = !cred.revoked &&
            (cred.expiresAt == 0 || cred.expiresAt > block.timestamp);

        return (isValid, cred.issuer, cred.issuedAt, cred.expiresAt);
    }

    /**
     * @notice Verify a credential by its ID
     */
    function verifyById(bytes32 credentialId)
        external
        view
        returns (bool valid, Credential memory credential)
    {
        credential = _credentials[credentialId];
        if (credential.issuedAt == 0) return (false, credential);

        valid = !credential.revoked &&
            (credential.expiresAt == 0 || credential.expiresAt > block.timestamp);
    }

    /**
     * @notice Get all credential IDs for an engineer
     */
    function getEngineerCredentials(address engineer)
        external
        view
        returns (bytes32[] memory)
    {
        return _engineerCredentials[engineer];
    }

    /**
     * @notice Revoke a credential
     */
    function revokeCredential(bytes32 credentialId)
        external
        onlyRole(ISSUER_ROLE)
        whenNotPaused
    {
        Credential storage cred = _credentials[credentialId];
        if (cred.issuedAt == 0) revert CredentialNotFound(credentialId);
        if (cred.revoked) revert CredentialAlreadyRevoked(credentialId);

        cred.revoked = true;
        emit CredentialRevoked(credentialId, msg.sender);
    }

    function totalCredentials() external view returns (uint256) {
        return _totalCredentials;
    }

    function pause() external onlyRole(PAUSER_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    function _authorizeUpgrade(address newImplementation)
        internal
        override
        onlyRole(DEFAULT_ADMIN_ROLE)
    {}
}
