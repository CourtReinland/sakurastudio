using UnityEngine;
using System;
using System.Collections;
using SakuraMatch.Data;

namespace SakuraMatch.Core
{
    /// <summary>
    /// MonoBehaviour component for individual tiles in the match-3 grid.
    /// Handles visual representation and position management.
    /// Prefers catalog-imported sprites via <see cref="CatalogBindings"/>; falls back to solid colors.
    /// </summary>
    [RequireComponent(typeof(SpriteRenderer))]
    public class Tile : MonoBehaviour
    {
        private const float SelectionScaleMultiplier = 1.15f;
        private const float SwapDuration = 0.2f;

        private SpriteRenderer _spriteRenderer;
        private TileType _tileType;
        private Vector2Int _gridPosition;
        private bool _isSelected;
        private bool _isAnimating;
        private Vector3 _baseScale;
        private Sprite _defaultSprite;

        /// <summary>
        /// Gets the type of this tile.
        /// </summary>
        public TileType TileType => _tileType;

        /// <summary>
        /// Gets the grid position of this tile.
        /// </summary>
        public Vector2Int GridPosition => _gridPosition;

        /// <summary>
        /// Gets whether this tile is currently selected.
        /// </summary>
        public bool IsSelected => _isSelected;

        /// <summary>
        /// Gets whether this tile is currently animating.
        /// </summary>
        public bool IsAnimating => _isAnimating;

        /// <summary>
        /// Event fired when the tile animation completes.
        /// </summary>
        public event Action OnAnimationComplete;

        private void Awake()
        {
            _spriteRenderer = GetComponent<SpriteRenderer>();
            _baseScale = transform.localScale;
            _defaultSprite = _spriteRenderer.sprite;
            CatalogBindings.EnsureLoaded();
        }

        /// <summary>
        /// Initializes the tile with a type and grid position.
        /// </summary>
        /// <param name="tileType">The type of tile to create.</param>
        /// <param name="gridPosition">The position in the grid.</param>
        public void Initialize(TileType tileType, Vector2Int gridPosition)
        {
            _tileType = tileType;
            _gridPosition = gridPosition;
            UpdateVisuals();
        }

        /// <summary>
        /// Updates the grid position of the tile.
        /// </summary>
        /// <param name="newPosition">The new grid position.</param>
        public void SetGridPosition(Vector2Int newPosition)
        {
            _gridPosition = newPosition;
        }

        /// <summary>
        /// Moves the tile to a world position instantly.
        /// </summary>
        /// <param name="worldPosition">The target world position.</param>
        public void SetWorldPosition(Vector3 worldPosition)
        {
            transform.position = worldPosition;
        }

        private void UpdateVisuals()
        {
            if (CatalogBindings.TryGetTileSprite(_tileType, out var catalogSprite) && catalogSprite != null)
            {
                _spriteRenderer.sprite = catalogSprite;
                _spriteRenderer.color = Color.white;
                return;
            }

            // Color fallback when catalog has no sprite for this type.
            if (_defaultSprite != null)
            {
                _spriteRenderer.sprite = _defaultSprite;
            }
            _spriteRenderer.color = GetColorForType(_tileType);
        }

        private Color GetColorForType(TileType type)
        {
            return type switch
            {
                TileType.Red => new Color(0.9f, 0.2f, 0.2f),
                TileType.Blue => new Color(0.2f, 0.4f, 0.9f),
                TileType.Green => new Color(0.2f, 0.8f, 0.3f),
                TileType.Yellow => new Color(0.95f, 0.85f, 0.2f),
                TileType.Purple => new Color(0.6f, 0.2f, 0.8f),
                TileType.Orange => new Color(0.95f, 0.5f, 0.1f),
                _ => Color.white
            };
        }

        /// <summary>
        /// Sets the selection state of the tile.
        /// </summary>
        /// <param name="selected">Whether the tile should be selected.</param>
        public void SetSelected(bool selected)
        {
            _isSelected = selected;
            UpdateSelectionVisual();
        }

        private void UpdateSelectionVisual()
        {
            if (_isSelected)
            {
                transform.localScale = _baseScale * SelectionScaleMultiplier;
                _spriteRenderer.sortingOrder = 1;
            }
            else
            {
                transform.localScale = _baseScale;
                _spriteRenderer.sortingOrder = 0;
            }
        }

        /// <summary>
        /// Animates the tile moving to a target world position.
        /// </summary>
        /// <param name="targetPosition">The target world position.</param>
        public void AnimateToPosition(Vector3 targetPosition)
        {
            if (_isAnimating)
            {
                StopAllCoroutines();
            }
            StartCoroutine(AnimateMovement(targetPosition));
        }

        private IEnumerator AnimateMovement(Vector3 targetPosition)
        {
            _isAnimating = true;
            Vector3 startPosition = transform.position;
            float elapsed = 0f;

            while (elapsed < SwapDuration)
            {
                elapsed += Time.deltaTime;
                float t = elapsed / SwapDuration;
                float smoothT = t * t * (3f - 2f * t); // Smoothstep
                transform.position = Vector3.Lerp(startPosition, targetPosition, smoothT);
                yield return null;
            }

            transform.position = targetPosition;
            _isAnimating = false;
            OnAnimationComplete?.Invoke();
        }
    }
}
